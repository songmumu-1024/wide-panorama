param(
    [int]$Port = 8000,
    [string]$Provider = ""
)

if ($Provider) { $env:IMAGE_PROVIDER = $Provider }
python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
