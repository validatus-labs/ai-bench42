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
| 3 — Coding & Tool Calling | Aufgabenerfolge, echte Tool Calls, Fehler, Laufzeit und Tokenverbrauch | Versionierte Auswahl aus SWE-bench Verified und BFCL; Runner/Evaluator im Aufbau |
| 4 — Melusine AgentBench | Eigenständige Pipeline-Implementierungen aus identischem Start-Commit | Getrennte Branches/Worktrees und tatsächlich isolierte Laufzeiten; unabhängiger Evaluator |

Phase 1/2 haben im AI-Model-Projekt bereits einen Kolibri-Performance-Pilot und
einen General-Evaluation-Smoke. Ein Smoke-Test ist keine vollständige
Qualitätsauswertung. Die vollständigen Vergleiche und Phase-3/4-Ausführung
erfordern die jeweils verifizierten Runner, Modellprofile und Audit-Gates.
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
