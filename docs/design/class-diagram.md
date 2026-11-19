# UML Class Diagram

Generated from the code at `632ae38`. GitHub and VS Code (with a Mermaid extension) render these
diagrams; export PNGs for the slides with <https://mermaid.live>.

## Model layer (persistence — `app/models.py`)

```mermaid
classDiagram
    direction LR
    class Device {
        +int id
        +str name «unique»
        +str management_ip
        +str platform = "cisco_ios"
        +int ssh_port = 22
        +datetime created_at
    }
    class ConfigVersion {
        +int id
        +int device_id
        +int version «unique per device»
        +str configuration
        +str source  (retrieval|pre_push|post_push|pre_rollback|rollback)
        +str operator
        +datetime created_at
    }
    class ConfigTemplate {
        +int id
        +str name «unique»
        +str configuration
        +datetime created_at
        +datetime updated_at
    }
    class PollSample {
        +int id
        +int device_id
        +datetime polled_at
        +bool reachable
        +float? rtt_ms
        +float? cpu_pct
        +float? memory_pct
        +float? in_bps
        +float? out_bps
    }
    class DeviceState {
        +int device_id «PK»
        +str state (up|down)
        +datetime last_poll_at
        +int consecutive_failures
    }
    class Alert {
        +int id
        +int device_id
        +str message
        +datetime raised_at
        +datetime? resolved_at
    }
    class InterfaceStatus {
        +int device_id «PK»
        +int index «PK»
        +str name
        +str oper_status (up|down)
        +float? speed_mbps
    }
    class TopologyLink {
        +int a «PK»
        +int b «PK»
    }
    class LogRecord {
        +int id
        +datetime timestamp
        +datetime received_at
        +str source
        +int? facility
        +int? severity
        +str body
        +str raw_message
        +bool parsed
    }
    class AuditRecord {
        +int id
        +datetime occurred_at
        +str actor
        +str action
        +str outcome
        +str? device_name
        +str detail
    }

    Device "1" *-- "0..*" ConfigVersion : versions
    Device "1" *-- "0..*" PollSample
    Device "1" *-- "0..1" DeviceState
    Device "1" *-- "0..*" Alert
    Device "1" *-- "0..*" InterfaceStatus
    Device "1" -- "0..*" TopologyLink : a / b
    AuditRecord ..> Device : names (kept after delete)
```

`*--` marks composition: deleting a device cascades to these rows. `AuditRecord` stores the device
**name**, not a foreign key, so audit history survives deletion (NFR-8). `LogRecord.source` is a
hostname string and is not linked to `Device`.

## Controller / domain layer

```mermaid
classDiagram
    direction TB
    class NetworkDeviceConnector {
        <<Protocol>>
        +retrieve(device) str
        +push(device, configuration) None
        +restore(device, configuration) None
    }
    class NetmikoConnector {
        -EnvironmentCredentials credentials
        -_run(device, operation, configuration) str
        +retrieve(device) str
        +push(device, configuration) None
        +restore(device, configuration) None
    }
    class EnvironmentCredentials {
        +get(device) dict
    }
    class Probe {
        <<Protocol>>
        +__call__(device) ProbeResult
    }
    class ProbeResult {
        <<dataclass>>
        +bool reachable
        +float? rtt_ms
        +float? cpu_pct
        +float? memory_pct
        +float? in_bps
        +float? out_bps
        +list~ProbeInterface~? interfaces
    }
    class probes {
        <<module>>
        +ping_probe(device) ProbeResult
        +snmp_probe(device, community) ProbeResult
        +combined_probe(device) ProbeResult
        -_previous_readings dict
    }
    class poller {
        <<module>>
        +poll_device(session, device, probe, now)
        +poll_all(session_factory, probe)
    }
    class config_templates {
        <<module>>
        +template_variables(text) list~str~
        +render_template(text, variables) str
    }
    class TemplateRenderError
    class SyslogReceivers {
        -servers
        -threads
        +start()
        +stop()
    }
    class syslog {
        <<module>>
        +parse_syslog(raw, received_at) ParsedMessage
        +persist_message(raw)
        +list_logs(session, filters) list~LogRecord~
    }
    class configuration {
        <<module>>
        +save_config_version(session, device_id, text, source, operator) ConfigVersion
        +record_audit_event(session, actor, action, outcome, device, detail) AuditRecord
    }
    class ConfigurationService {
        -Session session
        -NetworkDeviceConnector connector
        +retrieve(device, operator) ConfigVersion
        +push(device_ids, configuration, operator) list~ChangeResult~
        +rollback(device, target, operator) ChangeResult
        -_apply_change(device, kind, operator, apply) ChangeResult
    }
    class ChangeResult {
        <<dataclass>>
        +int device_id
        +ChangeStatus status
        +int? before_version
        +int? after_version
        +str? error
    }
    class DeviceError {
        +ChangeStatus status = "failed"
    }
    class DeviceUnreachableError
    class DeviceRejectedError
    class DeviceCredentialError
    class APIRoutes {
        <<FastAPI app/main.py + monitoring.router>>
        devices CRUD
        config retrieve/push/restore/versions
        templates CRUD + render
        logs, audit
        monitoring status/alerts/metrics/topology
    }

    NetworkDeviceConnector <|.. NetmikoConnector
    DeviceError <|-- DeviceUnreachableError
    DeviceError <|-- DeviceRejectedError
    DeviceError <|-- DeviceCredentialError
    DeviceCredentialError <|-- CredentialLookupError
    NetmikoConnector ..> DeviceError : raises
    ConfigurationService --> NetworkDeviceConnector
    ConfigurationService ..> ChangeResult
    ConfigurationService --> configuration
    APIRoutes --> ConfigurationService
    NetmikoConnector --> EnvironmentCredentials
    EnvironmentCredentials ..> CredentialLookupError : raises
    Probe <|.. probes : combined_probe
    probes ..> ProbeResult
    poller --> Probe
    poller ..> ProbeResult
    config_templates ..> TemplateRenderError : raises
    SyslogReceivers ..> syslog : persist_message
    APIRoutes --> NetworkDeviceConnector : app.state.device_connector
    APIRoutes --> configuration
    APIRoutes --> config_templates
    APIRoutes --> syslog
    APIRoutes --> poller : background task
```

## View layer (`web/src`)

`App` → `Layout` / `Sidebar` (from `nav.tsx`) → pages `Network`, `Logs`, `Devices`, `Push`,
`History`. Pages call `api` (`api/index.ts`), which resolves to `live.ts` (REST) or `mock.ts`
(same signatures). Shared UI primitives live in `components/ui/`.

## Design principles worth pointing out in the presentation

- **Dependency inversion.** Routes and the poller depend on `NetworkDeviceConnector` / `Probe`
  protocols, not on Netmiko or SNMP, so tests inject `FakeConnector` and fake probes.
- **Single responsibility.** Parsing (`parse_syslog`), transport (`SyslogReceivers`), and query
  (`list_logs`) are separate functions.
- **DRY / SRP (fixed in P-002).** Push and rollback share `ConfigurationService._apply_change`.
  Route handlers only validate input and map results to HTTP.
- **Exception hierarchy at the boundary.** Netmiko errors become `DeviceError` subclasses, each
  carrying a `status` and an operator-safe message, so the service never inspects library types.
- **Remaining.** `app/main.py` (385 lines) still holds device/template/log routes. Split it into routers (#19).
