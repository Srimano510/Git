Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.venv\Scripts\Activate.ps1

3llKGL8iahmnE22eSuKbSrEnPrNrK4Km4YQh7IN59PM

python -m scripts.mock_llm --log C:\demo\mock.jsonl

python -m nanobot gateway -c C:\demo\config.json

localhost:8775
