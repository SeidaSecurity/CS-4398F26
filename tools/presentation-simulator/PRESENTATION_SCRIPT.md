# CS 4398 — Two-person incident response presentation

**Presenter 1 (your friend):** “This dashboard is our network-management platform. Four virtual devices are registered: three active and the fourth on standby. We can manage them and push configurations through SSH.” Show **Inventory** and the topology; verify Standby-R4 is Down.

**Presenter 2 (you):** “I'll introduce an abnormal request surge to show how an operator detects and responds to capacity pressure.” Open the separate local controller and press **Generate Request Spike**. Return to **Network → All devices**. Point out modeled CPU and throughput, the fluctuating Network activity chart, stored warning/error severity chart, and Incident Intelligence guidance. Mention that this is an explicitly modeled load scenario; log delivery and configuration operations are live application workflows.

**Presenter 1:** “The system identifies the capacity problem and recommends enabling spare capacity. I will make that change using the platform's configuration management.” Open **Configuration → Push**, select **Standby-R4 only**, enter:

```text
interface GigabitEthernet0/1
no shutdown
```

Click Preview, review the target and snippet, and Push. Do **not** push to all devices.

**Presenter 2:** “The fourth device is now enabled. The monitoring charts show a reduced load on the primary, active warnings clear, and the rate of new severe events drops. We retain the historical incident logs for analysis.” Return to **Network** and **Inventory**, showing Standby-R4 Up.

**Key honesty point:** Routers run an IOS-like SSH emulator and modeled capacity telemetry. The configuration push and the syslog ingestion/API-to-UI flow use real application protocols and database records. Incident Intelligence is a transparent rule-based assistant, not a trained neural-network system.
