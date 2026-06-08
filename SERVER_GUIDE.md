# Руководство: сервер Windows

## 1. Обновление проекта на сервере

### Подключение
1. Откройте **Remote Desktop Connection** (`Win+R` → `mstsc`)
2. Введите IP-адрес сервера, подключитесь

### Обновление через Git
Откройте **PowerShell** или **cmd** в папке проекта на сервере:

```powershell
cd C:\VLK\MultiParser       # или ваш путь к проекту на сервере
git pull
```

Если git запрашивает логин — введите `88788788` и токен GitHub (не пароль аккаунта, а Personal Access Token из Settings → Developer settings → Tokens).

### Если изменились зависимости (requirements.txt)
```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Перезапуск парсера
Закройте текущее окно парсера и запустите заново (`wb_parser.exe` / `ozon_parser.exe`).

---

## 2. Загрузка логов с сервера (fetch_logs.ps1)

### Что делает скрипт
Копирует все файлы из папки `logs\` на сервере в папку `server_logs\` на локальной машине.  
Папка `server_logs\` не попадает в git (в `.gitignore`).

---

### Способ А — Общая папка Windows (рекомендуется, настраивается один раз)

#### Шаг 1. Расшарьте папку на сервере (один раз)
1. Подключитесь к серверу через RDP
2. Найдите папку `C:\VLK\MultiParser\logs` в Проводнике
3. Правой кнопкой → **Свойства** → вкладка **Общий доступ** → **Расширенная настройка**
4. Поставьте галочку **Открыть общий доступ к этой папке**
5. Имя папки — например `MultiParser_logs`
6. Нажмите **Разрешения** → дайте права **Чтение** для нужного пользователя (или Everyone)
7. ОК, Применить

#### Шаг 2. Настройте скрипт на локальной машине
Откройте `fetch_logs.ps1` в редакторе и замените строку:
```powershell
$SERVER_LOGS = "\\192.168.1.100\MultiParser\logs"
```
на:
```powershell
$SERVER_LOGS = "\\IP-СЕРВЕРА\MultiParser_logs"
```
Где `IP-СЕРВЕРА` — IP вашего Windows-сервера (например `192.168.1.50`).

Если нужен пароль — заполните:
```powershell
$SERVER_USER = "имя_пользователя"
$SERVER_PASS = "пароль"
```

#### Шаг 3. Запуск
```powershell
cd C:\VLK\MultiParser
.\fetch_logs.ps1
```
Если PowerShell ругается на политику выполнения:
```powershell
powershell -ExecutionPolicy Bypass -File .\fetch_logs.ps1
```

---

### Способ Б — Через RDP (без настройки, вручную)

1. В **Remote Desktop Connection** перед подключением:
   - Нажмите **Показать параметры** → вкладка **Локальные ресурсы** → **Подробнее**
   - Поставьте галочку на вашем диске **C:**
2. Подключитесь к серверу
3. На сервере в Проводнике ваш диск C: виден как `\\tsclient\C`
4. Скопируйте файлы из `C:\VLK\MultiParser\logs\` в `\\tsclient\C\VLK\MultiParser\server_logs\`

Или автоматически — на сервере выполните:
```powershell
robocopy C:\VLK\MultiParser\logs \\tsclient\C\VLK\MultiParser\server_logs /MIR
```

---

### Способ В — SSH (если установлен OpenSSH на сервере)

Проверить наличие SSH на сервере: `ssh имя@IP-сервера`

Если работает — в `fetch_logs.ps1` замените содержимое на:
```powershell
scp -r имя@IP-сервера:C:/VLK/MultiParser/logs/* .\server_logs\
```

---

## 3. Анализ логов с Claude

После запуска `fetch_logs.ps1` скажите Claude:
> «Прочитай логи из server_logs\ и проанализируй»

Claude сам найдёт и прочитает файлы.

---

## 4. Быстрая шпаргалка

| Действие | Команда |
|---|---|
| Обновить сервер | `git pull` (в папке проекта на сервере) |
| Скачать логи | `.\fetch_logs.ps1` (на локальной машине) |
| Push в GitHub | сказать Claude «запушь» или `git push` |
