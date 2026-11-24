#!/usr/bin/env python3
"""Small IOS-like SSH lab device for CS4398 (not Cisco IOS or CML).

The SSH protocol is real (Paramiko); the router CLI and configuration are emulated.
Bind only to 127.0.0.1 by default. Does not forward actual IP packets or produce SNMP.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

LOG = logging.getLogger("virtual_router")
DEFAULT_STATE = {
    "hostname": "Virtual-R1",
    "interfaces": {
        "GigabitEthernet0/0": {
            "description": "Emulated uplink (no packet forwarding)",
            "ip_address": "192.0.2.1 255.255.255.0",
            "shutdown": False,
        },
        "GigabitEthernet0/1": {"description": "Emulated LAN", "ip_address": None, "shutdown": True},
    },
    "extra_lines": [],
}


def safe_name(name: str) -> str:
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", name):
        raise ValueError("Hostname must start with a letter and contain only letters/numbers/-/_ (max 40)")
    return name


class RouterState:
    def __init__(self, path: Path, initial_name: str = "Virtual-R1") -> None:
        self.path = path
        self.lock = threading.RLock()
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            # Deep copy, so multiple instances don't share nested dicts.
            self.data = json.loads(json.dumps(DEFAULT_STATE))
            self.data["hostname"] = safe_name(initial_name)
            self.save()

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tempname = tempfile.mkstemp(prefix=".router-", dir=self.path.parent)
            try:
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(self.data, file, indent=2)
                    file.write("\n")
                os.replace(tempname, self.path)
            finally:
                if os.path.exists(tempname):
                    os.unlink(tempname)

    def running_config(self) -> str:
        with self.lock:
            lines = [
                "Building configuration...", "", "Current configuration:", "!",
                "version 15.9", "service timestamps log datetime msec", "!",
                f"hostname {self.data['hostname']}", "!",
            ]
            for iface, settings in self.data["interfaces"].items():
                lines.append(f"interface {iface}")
                if settings.get("description"):
                    lines.append(f" description {settings['description']}")
                if settings.get("ip_address"):
                    lines.append(f" ip address {settings['ip_address']}")
                lines.append(" shutdown" if settings.get("shutdown") else " no shutdown")
                lines.append("!")
            lines.extend(self.data.get("extra_lines", []))
            lines.extend(["!", "line vty 0 4", " login local", " transport input ssh", "!", "end"])
            return "\r\n".join(lines)

    def interfaces_brief(self) -> str:
        with self.lock:
            lines = ["Interface                  IP-Address      OK? Method Status                Protocol"]
            for iface, data in self.data["interfaces"].items():
                ip = (data.get("ip_address") or "unassigned").split()[0]
                status = "administratively down" if data.get("shutdown") else "up"
                protocol = "down" if data.get("shutdown") else "up"
                lines.append(f"{iface:<26} {ip:<15} YES manual {status:<21} {protocol}")
            return "\r\n".join(lines)


class RouterCLI:
    """One SSH interactive session; the underlying config is shared across clients."""

    def __init__(self, state: RouterState, enable_secret: str | None = None) -> None:
        self.state = state
        self.enable_secret = enable_secret
        self.mode = "exec"
        self.privileged = False
        self.interface: str | None = None
        self.awaiting_secret = False
        self.closed = False

    def prompt(self) -> str:
        name = self.state.data["hostname"]
        if self.awaiting_secret:
            return "Password: "
        if self.mode == "interface":
            return f"{name}(config-if)#"
        if self.mode == "config":
            return f"{name}(config)#"
        return f"{name}{'#' if self.privileged else '>'}"

    def _set_interface(self, cmd: str) -> str:
        name = cmd[len("interface "):].strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9/._:-]{0,60}", name):
            return "% Invalid interface name"
        with self.state.lock:
            self.state.data["interfaces"].setdefault(name, {
                "description": "", "ip_address": None, "shutdown": False
            })
            self.state.save()
        self.interface = name
        self.mode = "interface"
        return ""

    def execute(self, raw: str) -> str:
        cmd = raw.strip()
        lower = cmd.lower()
        if self.awaiting_secret:
            self.awaiting_secret = False
            if cmd == self.enable_secret:
                self.privileged = True
                return ""
            return "% Access denied"
        if not cmd:
            return ""
        if lower in ("exit", "logout", "quit"):
            if self.mode == "interface":
                self.mode = "config"
                self.interface = None
            elif self.mode == "config":
                self.mode = "exec"
            else:
                self.closed = True
            return ""
        if lower in ("end", "ctrl-z"):
            self.mode = "exec"
            self.interface = None
            return ""
        if lower in ("disable",):
            self.privileged = False
            self.mode = "exec"
            return ""
        if lower == "enable":
            if self.enable_secret and not self.privileged:
                self.awaiting_secret = True
            else:
                self.privileged = True
            return ""
        if lower in ("terminal length 0", "terminal width 511", "terminal width 0"):
            return ""
        if lower.startswith("terminal width ") or lower.startswith("terminal length "):
            return ""
        if lower in ("show running-config", "show run", "show startup-config", "show start"):
            return self.state.running_config()
        if lower in ("show ip interface brief", "show ip int brief", "show ip int br"):
            return self.state.interfaces_brief()
        if lower == "show version":
            return (
                "VirtualRouter Lab Software, Version 1.0 (CS4398 training emulator)\r\n"
                "This is not Cisco IOS and does not forward packets.\r\n"
                f"{self.state.data['hostname']} virtual management interface is online\r\n"
                "2 virtual GigabitEthernet interfaces"
            )
        if lower in ("show interfaces", "show interfaces status"):
            return self.state.interfaces_brief()
        if lower in ("show clock",):
            return time.strftime("%H:%M:%S UTC %a %b %d %Y", time.gmtime())
        if lower in ("write memory", "wr mem", "copy running-config startup-config"):
            self.state.save()
            return "Building configuration...\r\n[OK]"
        if lower in ("configure terminal", "conf t", "config terminal"):
            self.mode = "config"
            self.privileged = True
            return "Enter configuration commands, one per line. End with CNTL/Z."
        if self.mode in ("config", "interface"):
            if self.mode == "config" and lower.startswith("hostname "):
                try:
                    name = safe_name(cmd[len("hostname "):])
                except ValueError:
                    return "% Invalid input detected at '^' marker."
                with self.state.lock:
                    self.state.data["hostname"] = name
                    self.state.save()
                return ""
            if self.mode == "config" and lower.startswith("interface "):
                return self._set_interface(cmd)
            if self.mode == "interface" and self.interface:
                with self.state.lock:
                    iface = self.state.data["interfaces"][self.interface]
                    if lower.startswith("description "):
                        iface["description"] = cmd[len("description "):]
                    elif lower == "no description":
                        iface["description"] = ""
                    elif lower.startswith("ip address "):
                        parts = cmd.split()
                        if len(parts) != 4:
                            return "% Incomplete command."
                        try:
                            socket.inet_aton(parts[2])
                            socket.inet_aton(parts[3])
                        except OSError:
                            return "% Invalid input detected at '^' marker."
                        iface["ip_address"] = f"{parts[2]} {parts[3]}"
                    elif lower == "no ip address":
                        iface["ip_address"] = None
                    elif lower == "shutdown":
                        iface["shutdown"] = True
                    elif lower == "no shutdown":
                        iface["shutdown"] = False
                    else:
                        return "% Invalid input detected at '^' marker."
                    self.state.save()
                return ""
            # Accept only a small set of global config statements for a safe lab demo.
            if self.mode == "config" and (lower.startswith("ip route ") or lower.startswith("logging ") or lower.startswith("banner ")):
                with self.state.lock:
                    lines = self.state.data["extra_lines"]
                    if cmd not in lines:
                        lines.append(cmd)
                        self.state.save()
                return ""
            return "% Invalid input detected at '^' marker."
        return "% Invalid input detected at '^' marker."


def run_ssh(host: str, port: int, username: str, password: str, state: RouterState, host_key_path: Path) -> None:
    """Start an interactive SSHv2 endpoint backed by RouterCLI."""
    try:
        import paramiko
    except ImportError as exc:
        raise SystemExit("Paramiko missing: use ~/Documents/capstone/.venv/bin/python, or install paramiko") from exc

    class SSHServer(paramiko.ServerInterface):
        def __init__(self) -> None:
            self.shell_ready = threading.Event()

        def get_allowed_auths(self, _username: str) -> str:
            return "password"

        def check_auth_password(self, supplied_user: str, supplied_pass: str) -> int:
            if supplied_user == username and supplied_pass == password:
                return paramiko.AUTH_SUCCESSFUL
            return paramiko.AUTH_FAILED

        def check_channel_request(self, kind: str, chanid: int) -> int:
            return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_channel_pty_request(self, channel: Any, term: bytes, width: int, height: int,
                                      pixelwidth: int, pixelheight: int, modes: bytes) -> bool:
            return True

        def check_channel_shell_request(self, channel: Any) -> bool:
            self.shell_ready.set()
            return True

    if host_key_path.exists():
        key = paramiko.RSAKey.from_private_key_file(str(host_key_path))
    else:
        host_key_path.parent.mkdir(parents=True, exist_ok=True)
        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(str(host_key_path))
        os.chmod(host_key_path, 0o600)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(20)
    listener.settimeout(1.0)
    LOG.info("Virtual IOS-like SSH router listening at %s:%s", host, port)
    LOG.info("This emulator accepts configuration commands, but does not forward real packets")

    def handle(client: socket.socket, remote: tuple[str, int]) -> None:
        transport = paramiko.Transport(client)
        transport.add_server_key(key)
        server = SSHServer()
        try:
            transport.start_server(server=server)
            channel = transport.accept(12)
            if channel is None or not server.shell_ready.wait(10):
                return
            channel.settimeout(0.5)
            cli = RouterCLI(state)
            channel.send("\r\nCS4398 Virtual Router (IOS-like CLI, emulated)\r\n\r\n" + cli.prompt())
            buffer = ""
            prev_linebreak = False
            while transport.is_active() and not cli.closed:
                try:
                    data = channel.recv(2048)
                except socket.timeout:
                    continue
                if not data:
                    break
                for character in data.decode("utf-8", errors="replace"):
                    if character in "\r\n":
                        if character == "\n" and prev_linebreak:
                            prev_linebreak = False
                            continue
                        prev_linebreak = character == "\r"
                        channel.send("\r\n")
                        output = cli.execute(buffer)
                        buffer = ""
                        if output:
                            channel.send(output.replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n")
                        if cli.closed:
                            return
                        channel.send(cli.prompt())
                    elif character == "\x03":
                        buffer = ""
                        channel.send("^C\r\n" + cli.prompt())
                    elif character in "\b\x7f":
                        if buffer:
                            buffer = buffer[:-1]
                            channel.send("\b \b")
                    elif character.isprintable():
                        buffer += character
                        # Passwords for an optional enable secret are not echoed.
                        if not cli.awaiting_secret:
                            channel.send(character)
        except (EOFError, OSError) as exc:
            LOG.debug("SSH session %s closed: %s", remote, exc)
        except Exception:
            LOG.exception("SSH session %s failed", remote)
        finally:
            transport.close()
            try:
                client.close()
            except OSError:
                pass

    try:
        while True:
            try:
                client, remote = listener.accept()
            except socket.timeout:
                continue
            worker = threading.Thread(target=handle, args=(client, remote), daemon=True)
            worker.start()
    except KeyboardInterrupt:
        LOG.info("Stopped virtual router")
    finally:
        listener.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local SSH lab router for the CS4398 capstone (not CML)")
    parser.add_argument("--host", default="127.0.0.1", help="Listen address (default: loopback only)")
    parser.add_argument("--port", type=int, default=2222, help="SSH port (default: 2222)")
    parser.add_argument("--username", default="labadmin")
    parser.add_argument("--hostname", default="Virtual-R1")
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".cs4398-virtual-router")
    args = parser.parse_args()
    password = os.getenv("VROUTER_PASSWORD", "")
    if not password:
        raise SystemExit("Set VROUTER_PASSWORD in the environment (never put passwords in command arguments).")
    if args.host not in {"127.0.0.1", "127.0.0.2", "::1"}:
        raise SystemExit("For safety, this training emulator only binds loopback IPs.")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    state = RouterState(args.state_dir / "router.json", args.hostname)
    run_ssh(args.host, args.port, args.username, password, state, args.state_dir / "ssh_host_key")


if __name__ == "__main__":
    main()
