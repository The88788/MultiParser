# =============================================================================
# fetch_logs.ps1 — копирует логи с сервера в папку server_logs\ проекта
# =============================================================================
# Настройте переменные ниже, затем просто запускайте: .\fetch_logs.ps1
# =============================================================================

# --- НАСТРОЙКИ ---------------------------------------------------------------

# Путь к папке logs на сервере. Варианты:
#   UNC-путь (если сервер в сети):  "\\192.168.1.100\MultiParser\logs"
#   Буква диска (если подключён):   "Z:\MultiParser\logs"
#   RDP-диск (если включён в RDP):  "\\tsclient\C\VLK\MultiParser\logs"
$SERVER_LOGS = "\\192.168.1.100\MultiParser\logs"

# Куда класть локально (относительно расположения скрипта)
$LOCAL_LOGS  = "$PSScriptRoot\server_logs"

# Какие файлы копировать (* = все, или например "*.log")
$FILE_FILTER = "*"

# Учётные данные для сетевого пути (оставьте пустыми если не нужны)
$SERVER_USER = ""
$SERVER_PASS = ""

# =============================================================================

Write-Host "Копирование логов с сервера..."
Write-Host "  Откуда: $SERVER_LOGS"
Write-Host "  Куда:   $LOCAL_LOGS"
Write-Host ""

# Подключение с паролем (если заданы)
if ($SERVER_USER -and $SERVER_PASS) {
    $secPass = ConvertTo-SecureString $SERVER_PASS -AsPlainText -Force
    $cred    = New-Object System.Management.Automation.PSCredential($SERVER_USER, $secPass)
    try {
        New-PSDrive -Name "SrvLogs" -PSProvider FileSystem -Root $SERVER_LOGS -Credential $cred -ErrorAction Stop | Out-Null
        $SERVER_LOGS = "SrvLogs:\"
    } catch {
        Write-Host "[ERROR] Не удалось подключиться: $_" -ForegroundColor Red
        exit 1
    }
}

# Создаём локальную папку
if (-not (Test-Path $LOCAL_LOGS)) {
    New-Item -ItemType Directory -Path $LOCAL_LOGS | Out-Null
}

# Проверяем доступность сервера
if (-not (Test-Path $SERVER_LOGS)) {
    Write-Host "[ERROR] Путь недоступен: $SERVER_LOGS" -ForegroundColor Red
    Write-Host "Проверьте: сеть, права доступа, правильность пути в переменной `$SERVER_LOGS" -ForegroundColor Yellow
    exit 1
}

# Копируем с помощью robocopy (умный инкрементальный копировщик)
$robocopyArgs = @(
    $SERVER_LOGS,
    $LOCAL_LOGS,
    $FILE_FILTER,
    "/MIR",    # Зеркальная синхронизация (удаляет файлы которых нет на сервере)
    "/Z",      # Возобновляемый режим
    "/NP",     # Без прогресс-бара
    "/NDL",    # Без имён папок
    "/LOG+:$LOCAL_LOGS\_fetch.log"  # Лог копирования
)

robocopy @robocopyArgs

$exitCode = $LASTEXITCODE
if ($exitCode -le 1) {
    # 0 = ничего не изменилось, 1 = скопированы новые файлы — оба успех
    $files = (Get-ChildItem $LOCAL_LOGS -File -Filter $FILE_FILTER -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "_fetch.log" }).Count
    Write-Host ""
    Write-Host "[OK] Готово. Файлов в server_logs\: $files" -ForegroundColor Green
} elseif ($exitCode -le 7) {
    Write-Host ""
    Write-Host "[OK] Скопировано с предупреждениями (код $exitCode)" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "[ERROR] Ошибка копирования (код $exitCode)" -ForegroundColor Red
    exit 1
}

# Отключаем временный диск
if (Get-PSDrive -Name "SrvLogs" -ErrorAction SilentlyContinue) {
    Remove-PSDrive -Name "SrvLogs"
}
