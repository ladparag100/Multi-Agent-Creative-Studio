# Contributing

Thanks for your interest in improving AI Creative Studio.

## What is welcome

- Fixes to bugs in the agents or deploy scripts.
- Clarifications to the README and published guide.
- Improvements to the developer experience (better error messages, clearer defaults).
- Updates that keep dependencies and Google Cloud APIs current.

Please keep pull requests focused. One logical change per pull request is much easier to review than a large mixed one.

## Development setup

1. Fork and clone the repository.
2. Work in `creative-studio/starter/`: `uv sync`, then `cp .env.example .env` and fill in your values.
3. Run the agents locally with `uv run adk web agents --allow_origins='*'`.

See the [README](README.md) for full prerequisites, configuration, and deployment instructions.

## Pull request guidelines

- Describe what you changed and why. If it changes behavior, explain the before and after.
- Match the style of the surrounding code; do not reformat unrelated files.
- If you change the guide content in `docs/`, remember that `docs/` is the GitHub Pages source, so changes go live on merge to `main`.
- Do not commit secrets or a populated `.env`.

## Code of Conduct

By participating you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions are licensed under the project's [Apache License 2.0](LICENSE).
