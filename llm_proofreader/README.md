## Translation String Vandalism Detection Script

The `llm_proofreader.py` script detects vandalism in Electrum translations using an LLM (OpenAI-compatible API).

gemini-3-flash-preview works well (passes the unittests) and costs roughly ~0.02 USD cent per translation prompt.

### Full Scan Mode

Scans all .po files in a locale directory:

```bash
./llm_proofreader.py --openai-url https://api.ppq.ai --openai-key sk-ABCD --model google/gemini-3-flash-preview --locale-dir locale
```

Single locale:

```bash
./llm_proofreader.py --openai-url https://api.ppq.ai --openai-key sk-ABCD --model google/gemini-3-flash-preview --locale-dir locale/eo_UY
```

### Diff Mode (Pull Request Proofreading for CI)

Checks only changed or added translations from a unified diff. This is the mode used by CI.

From a diff file:

```bash
./llm_proofreader.py --diff path/to/changes.diff
```

From stdin (pipe from git):

```bash
git diff origin/master..HEAD -- locale/ | ./llm_proofreader.py --diff -
```

From two commit refs directly:

```bash
./llm_proofreader.py --diff-commits 974d671 eab55b5
```

Exit code is 1 if any spam is detected, 0 otherwise. This allows CI to fail the build on vandalism.

### GitHub Actions Integration

The repository includes `.github/workflows/proofreader.yml` that runs the proofreader on every pull request. It diffs the PR branch against the default branch and checks only changed translations.

#### Setting up the OpenAI API secret

The `OPENAI_API_KEY` needs to be set as a repository secret in GitHub:
Settings → Secrets and variables → Actions → New repository secret → Name: `OPENAI_API_KEY`.

GitHub Actions does not expose secrets to workflows triggered by pull requests from forks, so the proofreader effectively only runs with the API key for PRs from collaborators with write access.

### Unittests

The unittests serve as a benchmark to verify an LLM is suitable for this task.

Running all tests (requires a live API key):

```bash
OPENAI_BASE_URL=https://api.ppq.ai OPENAI_MODEL=google/gemini-3-flash-preview OPENAI_API_KEY=sk-ABCD python3 -m unittest test_llm_proofreader
```

Running only the offline diff-parsing tests (no API queries):

```bash
python3 -m unittest -k DiffPars -k UnescapePo -k TestExtract test_llm_proofreader
```
