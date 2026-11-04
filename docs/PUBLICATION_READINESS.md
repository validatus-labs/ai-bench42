# Publication Readiness — AI-Bench42

This checklist is for maintainers before switching this currently private repository to **public**.

## Hard gates — complete before visibility change

- [ ] **Repository/history secret scan:** audit the entire Git history and reachable refs, not only current `.gitignore` or the latest working tree. Review previous credentials, authenticated URLs, tokens, private addresses, keys, service configurations, log outputs, CI artifacts and historical branches.
- [ ] **Personal data and third-party rights:** verify committed files and history contain no private/real correspondence, hidden Gold, protected HPI/Quagga samples, unauthorized annotations, customer identifiers, proprietary model weights or unlicensed content. The existing `docs/HPI_TRAIN.md` deliberately requires a rights record.
- [ ] **Software licensing decision:** root `LICENSE` has not been confirmed. Choose a license for code and clarify whether reports, images and original datasets have separate terms. Publishing on GitHub does not by itself grant a reusable open-source license.
- [ ] **Security controls:** inspect workflows, releases, retained artifacts and all existing GitHub Actions logs. GitHub notes that these become visible when a repo is made public.
- [ ] **Reproducibility honesty:** preserve labels for unmeasured, blocked, partial and independently verified results; do not replace them with promotional success claims.
- [ ] **Image delivery and credit:** current README embeds a third-party Unsplash URL. Confirm its rights and either self-host a compliant authorized copy or remove the remote embed according to the ALTONJI self-hosting policy.
- [ ] **Public links & disclosures:** check README, code, tool configs, test fixtures, docs, citations and release notes for information not approved for public sharing.
- [ ] **Versioned baseline:** choose a reviewed public commit; check whether history needs sanitization or a clean public export without sensitive previous commits. Merely deleting a tracked secret in the latest commit does not erase history.

## Discovery and community setup after clearance

- [ ] GitHub About description and 10–18 relevant Topics
- [ ] Link this repo and reader-facing reports from a stable public website
- [ ] Keep README, `llms.txt`, [Discovery](DISCOVERY.md), [Results](reports/README.md), and [Methodology](reports/methodology.md) mutually consistent
- [ ] Add release tag (suggested `v0.1.0-research-preview`) **only after** a reviewed reproducible commit is frozen
- [ ] Add an explicit license and, if appropriate, a citation file and security disclosure policy
- [ ] Verify from an **unauthenticated browser** that key files are accessible and that claims match reported evidence
- [ ] Check GitHub search; treat external search and AI-index discovery as best effort, not instant guarantees

## Current scope

The work in this branch is documentation/discovery preparation only. No model evaluations, worker code, benchmark freezes, repository visibility, protected datasets, or production deployments are modified.
