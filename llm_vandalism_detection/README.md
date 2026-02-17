## translation string vandalism detection script

The `llm_vandalism_detection.py` script is intended to detect vandalism in the Electrum translations.

It can be run against a local Ollama model or against an OpenAI API compatible LLM API provider.

gemini-3-flash-preview seems to work well (it passes the unittests) and costs roughly ~0.02 usd cent per translation (prompt).

Usage Example:
```bash
$ ./llm_vandalism_detection/llm_vandalism_detection.py --api openai --openai-url https://api.ppq.ai --openai-key sk-ABCD --model google/gemini-3-flash-preview --locale-dir locale/eo_UY
SPAM: Close -> Fermi
Report written: vandalism_reports/vandalism_report_eo_UY.json

Scanned: 1 locales
Skipped: 0 locales (reports already exist)
Total spam found: 1

Summary report written to: vandalism_reports/vandalism_report_summary.txt
Summary JSON written to: vandalism_reports/vandalism_report_summary.json

$ ls vandalism_reports
vandalism_report_eo_UY.json  vandalism_report_summary.json  vandalism_report_summary.txt

$ cat cat vandalism_reports/vandalism_report_eo_UY.json 
{
  "generated": "2026-02-17T16:08:55.289813",
  "locale": "eo_UY",
  "total_spam": 1,
  "entries": [
    {
      "locale": "eo_UY",
      "original_str": "Close",
      "translation": "Fermi"
    }
  ]
}
```

### Unittests

The unittests act as some form of benchmark to check if a LLM is suitable to run this check.

Running the unittests:
```bash
API_BACKEND=openai OPENAI_BASE_URL=https://api.ppq.ai OPENAI_MODEL=google/gemini-3-flash-preview OPENAI_API_KEY=ABC python3 -m unittest test_vandalism_detection.py
```
