# Screening evaluation

Provider mode: **demo**. Generated 2026-11-18T02:25:35.764694+00:00.

Evaluated 20 fictional resumes, split between PDF and DOCX, against three jobs.

| Measurement | Observed result |
| --- | --- |
| Exact scalar field accuracy (name, email, experience, location, notice, salary) | 100.0% |
| Expected skill recall | 73.2% |
| Accepted quotes found verbatim in their source | 103/103 |
| Processing failures | 0 |

| Job | Evidence matcher precision@5 | Keyword baseline precision@5 |
| --- | --- | --- |
| Python Backend Engineer | 100% | 100% |
| Frontend Engineer | 100% | 100% |
| Full-stack Product Engineer | 80% | 80% |

## Interpretation

Demo mode uses deterministic term matching; these results are **not Gemini accuracy measurements**.
Run `python scripts/evaluate.py --mode gemini --confirm-synthetic` after configuring a free-tier model to measure that provider.
Only extraction and matching are evaluated; human decisions are never automated.

The fixtures and relevance labels were authored together by the project author. They are small,
synthetic, and not independently annotated or representative of hiring performance. Skill recall
does not measure false-positive skills. Verbatim source validation proves a quote exists, not that
the interpretation is correct. A keyword-heavy resume can still mislead the demo matcher.
Top-five ties are broken by candidate ID for reproducibility. Review both results and limitations
before making claims in a portfolio presentation.
