# Melusense Benchmark

Reproduzierbarer A/B/C-Benchmark für **Kolibri-1, Mistral Small 4 und Qwen**:
Serving-Performance, allgemeine Modellqualität, Coding/Tool Calling und die
eigenständige Entwicklung derselben Melusine-Pipeline werden getrennt bewertet.

Dieses private Repository enthält die agentensichtbare Entwicklungsaufgabe und
ein absichtlich unvollständiges Startgerüst. Die Infrastruktur und die
Coordinator-Runner werden im separaten AI-Model-Projekt geführt. Die hier
vorhandenen Parser-Stubs sind keine Referenzimplementierung.

## Einstieg

- [MANIFEST.md](MANIFEST.md): Navigation.
- [AGENTS.md](AGENTS.md): verbindliche Agentenregeln.
- [TASKS.md](TASKS.md): gemeinsame Aufgaben und Phasen-Checkliste.
- [API-Vertrag](docs/contract.md): Schnittstellen und Sicherheitsinvarianten.
- [Evaluationsvertrag](docs/evaluation.md): Vergleichbarkeit und Isolation.
- [Gemeinsame Budgets](config/budget.json): gleiche Grenzen für alle Modelle.

## Vier Phasen

| Phase | Umfang | Werkzeug / Ausführung |
|---|---|---|
| 1 — Infrastructure & Metrics | Modellrevision, Quantisierung, Kontext, Speicher, TTFT, Prefill, Decode, Cache, 1/2/4 gleichzeitige Clients | vLLM, ein zentraler Prometheus, NVIDIA AIPerf; Coordinator-Runner in AI-Model |
| 2 — General Evaluation | Instruktionsbefolgung, Wissen und Reasoning mit festen Aufgaben, Dataset-Revisionen und Bewertungsregeln | Hugging Face LightEval mit IFEval, MMLU-Pro und BBH; Coordinator-Runner in AI-Model |
| 3 — Coding & Tool Calling | Aufgabenerfolge, echte Tool Calls, Fehler, Laufzeit und Tokenverbrauch | Versionierte SWE-bench-/BFCL-Auswahl und Runner in AI-Model; Kolibri-Pilot 9/9 korrekte Tool Calls; SWE-Images aktuell ohne ARM64 |
| 4 — Melusine AgentBench | Eigenständige Pipeline-Implementierungen aus identischem Start-Commit | Neun Branches/Worktrees vorbereitet; Tool-/Evaluator-Container geprüft, Freeze und separater Referenz-/Gold-Evaluator implementiert; reale Agentenläufe an Gates gebunden |

Im AI-Model-Projekt sind ein Kolibri-Performance-Pilot, ein General-Evaluation-Smoke
und ein BFCL-Pilot ausgeführt: drei einfache Python-Tool-Fälle mit je drei Seeds,
9/9 vom offiziellen AST-Checker akzeptiert und lokal als erlaubte reine Funktionen
ausgeführt. Dieser kleine Single-Turn-Test ist kein vollständiger BFCL-Score.
Die drei eingefrorenen SWE-bench-Images bieten aktuell AMD64, kein ARM64; auf der
Spark bleibt deren Ausführung blockiert, ohne Emulation oder stillen Falltausch.

Für Melusine sind je drei Branches/Worktrees für Kolibri, Mistral und Qwen aus
identischem Basis-SHA angelegt. Die Kandidaten erhalten Git-freie Exporte.
Neun reale Tool-/Evaluator-Container bestehen je 14 Abschottungsprüfungen.
Das attestiert noch nicht den sichtbaren Kilo-Worker samt Modell-Gateway.
Referenz-Freeze, qualifizierte menschliche Gold-Daten, unabhängige Worker-Isolation
und qualifizierte weitere Modellprofile fehlen noch. Es gibt keine gestarteten
Melusine-Modellversuche, keinen realen Melusine-F1 und keinen fertigen A/B/C-Vergleich.

Die Coordinator-Befehle in AI-Model sind coding.py mit prepare/bfcl/swe-preflight/
swe-evaluate und agentbench.py mit prepare/status/probe/handoff/freeze/evaluate.
Der Freeze sichert einen Git-Tree ohne Commit/Push; der getrennte Evaluator
vergleicht eingefrorene Kandidaten und eine unabhängig freigegebene Referenz
gegen private geprüfte Gold-Daten. Er bewahrt Fehler und exportiert nur Aggregate.
Künftige Worker bleiben in der sichtbaren Kilo-VS-Code-Sitzung; kein versteckter
Agentenloop wird als Ersatz gestartet.
Dieses Startgerüst allein startet keine SWE-bench-, BFCL- oder Agentenläufe.

## Gemeinsamer Ausgangspunkt

Der eingefrorene Ausgangs-Commit ist:

```text
75fcaad909346909115d92b9929b5b91b3ddfbd6
Branch: benchmark/base-v1
Tag:    benchmark-base-v1
```

Alle Modellversuche müssen diesen **vollständigen SHA** verwenden. Der Hauptbranch
entwickelt die Projektdokumentation weiter und ist kein Ersatz für den Basis-SHA.
GitHub-Schreibschutz ist im aktuellen privaten Tarif nicht verfügbar; der
Coordinator muss die Referenzen vor jedem Lauf gegen den SHA prüfen.

Jedes Modell erhält dieselbe TASKS.md, sichtbare Tests und Budgets. Mindestens
drei unabhängige Wiederholungen erhalten jeweils eigene Run-IDs. Modellversion,
Quantisierung, Kontext, Decoding-Parameter, Toolversionen, Laufzeit, Tokenverbrauch
und Fehler werden protokolliert. Keine früheren Lösungen, Agentenverläufe oder
geänderten Dateien werden übernommen. Gleiche Vorbereitung und Bewertung
verlangen keine identischen stochastischen Modellausgaben.

## Startgerüst prüfen

Python >=3.12 ist die Zielumgebung. Die initialen Quellen verwenden nur die
Standardbibliothek:

```bash
python3 -B tools/verify_scaffold.py
python3 -B -m unittest discover -s tests -p 'test_scaffold.py'
python3 -B -m unittest discover -s tests -p 'test_acceptance.py'
```

Die ersten beiden Befehle prüfen das Startgerüst. Der letzte Befehl scheitert
auf der eingefrorenen Basis erwartungsgemäß an den unimplementierten Parsern.
Diese sichtbaren Abnahmetests sind unverändert zu erfüllen; ein grüner
Strukturcheck ist kein Parser-Erfolg. Fehlgeschlagene Tests dürfen nicht zur
Ergebnisverbesserung gelöscht, übersprungen oder abgeschwächt werden.

## Architektur und Isolationsgrenzen

Ein zentraler Prometheus sammelt die Metriken des jeweils laufenden
Modellservers. Ein Worktree benötigt keinen eigenen Prometheus. Große Modelle
werden auf der DGX Spark nacheinander geprüft; gleichzeitige Clients und
tatsächlich aktive Modellsequenzen müssen getrennt ausgewiesen werden.

Die vollständige Referenz bleibt im separaten Repository
`validatusinternal/melusense`. Branches und Worktrees sind keine Zugriffssperre.
Agenten dürfen weder die Referenz noch andere Versuche, Host-Zugangsdaten,
private Korpora, Gold oder versteckte Tests erreichen. Diese Isolation muss
außerhalb von Git tatsächlich geprüft werden.

Nur der unabhängige Evaluator verwendet zugelassene zusätzliche Prüfdaten.
Er bewertet vorher eingefrorene Kandidaten; der Worker zertifiziert seinen
eigenen Erfolg nicht. Rechte-/Datenschutzprüfung und unabhängige menschliche
Gold-Annotationen bleiben verbindliche Gates.

Die drei sichtbaren Beispiele sind synthetisch. Reale E-Mails, private
Annotationen, Referenzcode, Geheimnisse und frühere Modelllösungen gehören
nicht in dieses Repository. Eine spätere Veröffentlichung auf ALTONJI oder
Hugging Face setzt gesonderte Prüfung und Freigabe voraus.
