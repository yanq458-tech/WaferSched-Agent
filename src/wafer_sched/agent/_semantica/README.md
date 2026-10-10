# Preserved Semantica context subset

These 12 Python modules are unmodified copies of the project's existing
`.venv/vendor/semantica/semantica/` source. They provide the real `AgentMemory`
and `ContextGraph` implementations and their minimal import closure. See
`PROVENANCE.json` for file hashes and `LICENSE` for Semantica's MIT notice.

Upstream project: https://github.com/semantica-agi/semantica

Only the three package initialization files are new, minimal namespace wrappers.
The full upstream context initializer imports unrelated retrieval/analytics
modules. This subset does not register itself as an installed `semantica` package,
replace the platform's Semantica installation, or implement an imitation memory.
Advanced KG analytics and vector stores are disabled; these optional operations
are outside the tested subset. Runtime dependencies here are numpy and PyYAML.

The old package reports version 0.7.0 and a local vendor install. There is no
independent Git metadata in that vendor directory. The platform's upstream lock
commit is a provenance reference, not proof these source files match that commit.
The delivered hashes identify the exact source used for reproducible stage-six
experiments without requiring a working old virtual environment.
