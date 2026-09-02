# TuxInDrive 0.26.31 and Network Lab 0.26.31.5 media kit

These drafts describe the current code and independently versioned Network Lab
package. Before posting, replace the download link with the final immutable
GitHub Release URL and confirm that its package checksum matches the published
asset. Disclose that you maintain TuxInDrive, adapt the opening to the community,
and avoid posting the same text into unrelated conversations.

![TuxInDrive Network Lab visual overview](assets/network-lab-0.26.31.5.svg)

## Verified facts

- Desktop/server release: TuxInDrive `0.26.31`.
- Test-tool release: Network Lab `0.26.31.5`, Debian version `0.26.31+lab5`.
- Network Lab is a separate Linux application and release channel; it never
  replaces or enters the updater channel for the desktop client or server.
- Its resizable GTK window shows Alice (`127.0.0.2`), the production-protocol
  server (`127.0.0.1`) and Bob (`127.0.0.3`), live scenario progress, active
  links, results, connection count and byte count.
- It runs 19 bounded functional scenarios covering authentication, security
  headers, routing, tenant isolation, mailbox/object/rendezvous/collaboration
  flows, invalid inputs, concurrency, quota recovery, MCP read-only behavior,
  audit events and restart durability.
- One scenario opens two real parallel TCP/HTTP connections from distinct
  loopback source addresses and transfers fictional 128 KiB objects through
  the production TuxInDrive server implementation.
- The listener is restricted to loopback. The lab loads no real accounts,
  credentials, synchronized folders or Internet endpoint, and writes private,
  redacted reports.
- Network Lab is a deterministic protocol/lifecycle tool. It does not claim to
  reproduce a cloud provider, NAT, public TLS, FUSE, physical bandwidth,
  Internet latency or packet loss.
- TuxInDrive 0.26.31 additionally improves restart scheduling and durable
  synchronization baseline reuse, reduces unchanged Android copying and
  repeated metadata work, caches macOS traffic sampling, and reserves 50% of
  the configured bandwidth ceiling for other applications by default. Existing
  explicit bandwidth settings remain unchanged.

## Release-page summary

TuxInDrive Network Lab 0.26.31.5 is a separate Linux test application for
repeatable server/client protocol validation. Its visual topology follows two
fictional clients as they exercise the production TuxInDrive server over an
ephemeral loopback listener. The application reports progress across 19
functional scenarios, opens real multi-address loopback TCP/HTTP connections,
and stores private human-readable, JSONL and summary logs. It never loads cloud
accounts, desktop synchronization folders or an external network endpoint.

Install the separately downloaded package with:

```bash
sudo apt install ./tuxindrive-network-lab_0.26.31+lab5_all.deb
```

## Short social post

I maintain TuxInDrive, an open-source multi-cloud sync client. The new Network
Lab 0.26.31.5 makes its server tests visible: Alice and Bob run 19 functional
scenarios through the real production protocol, including parallel traffic
from two loopback addresses. It uses fictional data, no cloud accounts and no
Internet route. Testers and contributors are welcome:
https://github.com/tpluharik/Tuxindrive

## Mastodon/X-sized post

TuxInDrive Network Lab 0.26.31.5: a visual Linux test app running 19 bounded
server/client scenarios over the production protocol. Real parallel loopback
traffic, fictional data, private reports, no accounts or Internet route. I
maintain the project; testers welcome. https://github.com/tpluharik/Tuxindrive

## Forum or Reddit post

I maintain TuxInDrive, an open-source, Linux-first multi-cloud synchronization
client. I wanted server/network testing to be understandable without reading a
test log, so the separately released Network Lab now has a live topology view.

It shows two fictional clients—Alice on `127.0.0.2` and Bob on `127.0.0.3`—as
they run 19 functional scenarios through the production server on `127.0.0.1`.
This includes authentication failures, tenant isolation, mailbox and object
flows, collaboration ordering, invalid inputs, concurrent clients, quota
recovery and restart durability. One scenario establishes real parallel
TCP/HTTP connections from both client addresses and sends bounded fictional
objects through the server.

The lab is deliberately local: it does not load cloud credentials or sync
folders, and it has no external-network target. It is not a substitute for
real-provider, NAT, public-TLS, FUSE or adverse-network testing. I would value
feedback on the usefulness of the visual progress, missing protocol scenarios,
and reproducibility on Ubuntu/Debian systems:
https://github.com/tpluharik/Tuxindrive

## LinkedIn/project update

TuxInDrive's newest testing component turns an otherwise opaque integration
suite into a visible local network exercise. Network Lab 0.26.31.5 displays two
fictional clients, the production-protocol server, active connections, progress
and results while it runs 19 bounded scenarios. It also generates real parallel
TCP/HTTP traffic across three loopback addresses, without using personal files,
cloud credentials or an Internet endpoint.

The main 0.26.31 release also focuses on responsible background behavior:
restart-aware scheduling, reusable synchronization baselines, less unchanged
Android copying, reduced duplicate metadata work and a 50% default bandwidth
reserve for other applications. TuxInDrive is open source, and testing,
technical review and contributions are welcome:
https://github.com/tpluharik/Tuxindrive

## Developer-oriented post

TuxInDrive Network Lab 0.26.31.5 exercises the real HTTP server implementation
with an ephemeral SQLite store and loopback listener. Its 19-scenario matrix
covers public/private health boundaries, authentication, tenant isolation,
mailbox, content-addressed objects, rendezvous, ordered collaboration, bounded
concurrency, quotas, read-only MCP and restart persistence. A multi-address
scenario binds clients to `127.0.0.2` and `127.0.0.3`, runs parallel requests
against `127.0.0.1`, and verifies the returned bytes and digests. Reports are
private and omit tokens and opaque payload contents. Review and scenario ideas
are welcome: https://github.com/tpluharik/Tuxindrive

## Suggested image text and alt text

**Caption:** TuxInDrive Network Lab 0.26.31.5 visualizes two fictional clients
running 19 production-protocol scenarios over real local loopback connections.

**Alt text:** Purple TuxInDrive Network Lab diagram showing Alice at
127.0.0.2 and Bob at 127.0.0.3 connected to a TuxInDrive production-protocol
server at 127.0.0.1. Three labels state 19 functional scenarios, real loopback
traffic and fictional data only.

## Common questions

- **Does it contact the Internet?** No. The automated listener and targets are
  loopback addresses. The package must still be downloaded separately.
- **Does it use my TuxInDrive configuration?** No. It creates a private
  temporary sandbox and fictional tenants.
- **Is the traffic simulated?** The data and users are fictional, but the
  multi-address scenario creates real local TCP/HTTP connections and passes the
  bytes through the production server implementation.
- **Does this prove cloud-provider or NAT compatibility?** No. Those remain
  explicit manual/VM release checks.
- **Can it replace the normal TuxInDrive package?** No. It has a separate Debian
  identity, version, launcher and release tag namespace.
- **What should a bug report include?** Review and attach `summary.json` plus the
  JSONL log. Remove any unrelated personal paths visible in a screenshot.

## Localized short posts

### Czech

Vyvíjím open-source synchronizační klient TuxInDrive. Nový Network Lab
0.26.31.5 názorně spouští 19 funkčních scénářů přes skutečný produkční protokol,
včetně paralelního provozu ze dvou loopback adres. Používá jen fiktivní data,
žádné cloudové účty ani internetové spojení. Testeři a přispěvatelé jsou vítáni:
https://github.com/tpluharik/Tuxindrive

### German

Ich entwickle TuxInDrive, einen quelloffenen Multi-Cloud-Sync-Client. Das neue
Network Lab 0.26.31.5 visualisiert 19 funktionale Szenarien über das echte
Produktionsprotokoll, einschließlich parallelem Datenverkehr von zwei
Loopback-Adressen. Nur fiktive Daten, keine Cloud-Konten und keine
Internetverbindung. Tests und Beiträge sind willkommen:
https://github.com/tpluharik/Tuxindrive

### French

Je maintiens TuxInDrive, un client open source de synchronisation multi-cloud.
Le nouveau Network Lab 0.26.31.5 visualise 19 scénarios fonctionnels utilisant
le véritable protocole de production, dont un trafic parallèle depuis deux
adresses de bouclage. Données fictives uniquement, sans compte cloud ni accès
Internet. Tests et contributions sont bienvenus :
https://github.com/tpluharik/Tuxindrive

### Spanish

Mantengo TuxInDrive, un cliente de sincronización multinube de código abierto.
El nuevo Network Lab 0.26.31.5 visualiza 19 escenarios funcionales con el
protocolo real de producción, incluido tráfico paralelo desde dos direcciones
de bucle local. Solo usa datos ficticios, sin cuentas en la nube ni conexión a
Internet. Se agradecen pruebas y contribuciones:
https://github.com/tpluharik/Tuxindrive

### Arabic

أعمل على تطوير TuxInDrive، وهو عميل مفتوح المصدر لمزامنة خدمات سحابية متعددة.
يعرض Network Lab 0.26.31.5 بصريًا 19 سيناريو وظيفيًا باستخدام بروتوكول الإنتاج
الفعلي، بما في ذلك اتصالات متوازية من عنواني loopback. يستخدم بيانات افتراضية
فقط، من دون حسابات سحابية أو اتصال بالإنترنت. نرحب بالمختبرين والمساهمين:
https://github.com/tpluharik/Tuxindrive

### Hebrew

אני מתחזק את TuxInDrive, לקוח קוד פתוח לסנכרון בין שירותי ענן. Network Lab
0.26.31.5 החדש מציג 19 תרחישים פונקציונליים דרך פרוטוקול הייצור האמיתי, כולל
תעבורה מקבילית משתי כתובות loopback. נעשה שימוש בנתונים בדויים בלבד, ללא
חשבונות ענן וללא חיבור לאינטרנט. נשמח לבודקים ולתורמים:
https://github.com/tpluharik/Tuxindrive

## Publication checklist

1. Publish the Network Lab package only under a `network-lab-v0.26.31.5` tag.
2. Verify the immutable asset name, Debian identity, checksum and 19/19 result.
3. Use the visual asset in this directory and its supplied alt text.
4. Link to the exact release or documentation page, not an expiring Actions
   artifact.
5. Record published URLs here or in the release issue to avoid duplicate posts.
