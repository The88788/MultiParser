TG_GUIDE_HTML = """\
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Подключение Telegram-уведомлений — {{APP_DEVELOPER}}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      font-size: 15px;
      line-height: 1.7;
      color: #e2e8f0;
      min-height: 100vh;
      background: linear-gradient(135deg, #0f0c29 0%, #1a1a4e 40%, #24243e 100%);
    }

    .wrapper {
      max-width: 820px;
      margin: 0 auto;
      padding: 40px 24px 0;
    }

    .page-header {
      text-align: center;
      padding: 48px 32px 36px;
      background: linear-gradient(135deg, rgba(74,168,216,.18) 0%, rgba(100,77,192,.18) 100%);
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 20px;
      margin-bottom: 32px;
      backdrop-filter: blur(8px);
    }
    .page-header .tg-icon {
      font-size: 52px;
      display: block;
      margin-bottom: 14px;
      filter: drop-shadow(0 0 18px rgba(74,168,216,.6));
    }
    .page-header h1 {
      font-size: 26px;
      font-weight: 700;
      color: #e8f4fd;
      letter-spacing: -.3px;
      margin-bottom: 8px;
    }
    .page-header p { color: #94b4cc; font-size: 14px; }

    .card {
      background: rgba(255,255,255,.05);
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 16px;
      padding: 28px 32px;
      margin-bottom: 20px;
      backdrop-filter: blur(4px);
      transition: border-color .2s;
    }
    .card:hover { border-color: rgba(74,168,216,.3); }
    .card h2 {
      font-size: 17px;
      font-weight: 600;
      color: #c9dff0;
      margin-bottom: 18px;
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .step { display: flex; gap: 16px; margin-bottom: 20px; }
    .step:last-child { margin-bottom: 0; }
    .step-num {
      flex-shrink: 0;
      width: 34px; height: 34px;
      border-radius: 50%;
      background: linear-gradient(135deg, #4aa8d8, #644dc0);
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 14px; color: #fff;
      margin-top: 2px;
      box-shadow: 0 0 12px rgba(74,168,216,.35);
    }
    .step-body { flex: 1; }
    .step-body strong { color: #e8f4fd; }
    .step-body p { color: #b0c8de; margin-top: 4px; }
    .step-body code {
      display: inline-block;
      background: rgba(0,0,0,.35);
      border: 1px solid rgba(255,255,255,.1);
      border-radius: 6px;
      padding: 1px 8px;
      font-family: 'Consolas', 'Fira Code', monospace;
      font-size: 13px; color: #7dd3fc; word-break: break-all;
    }
    .step-body .url-code { display: block; margin-top: 6px; padding: 8px 12px; font-size: 12.5px; }

    .callout {
      border-radius: 10px; padding: 13px 16px; margin-top: 10px;
      font-size: 14px; display: flex; gap: 10px; align-items: flex-start;
    }
    .callout .icon { flex-shrink: 0; font-size: 17px; margin-top: 1px; }
    .callout-info { background: rgba(74,168,216,.12); border-left: 3px solid #4aa8d8; color: #a8cfea; }
    .callout-warn { background: rgba(234,179,8,.10);  border-left: 3px solid #eab308; color: #d4b96a; }
    .callout-tip  { background: rgba(34,197,94,.10);  border-left: 3px solid #22c55e; color: #86c89a; }
    .callout strong { color: #e8f4fd; }

    .variant-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 6px; }
    .variant-card {
      background: rgba(0,0,0,.2);
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 12px; padding: 16px 18px;
    }
    .variant-card h3 { font-size: 14px; font-weight: 600; color: #e8f4fd; margin-bottom: 10px; }
    .variant-card h3 .badge {
      display: inline-block;
      background: linear-gradient(135deg,#22c55e,#16a34a);
      color: #fff; font-size: 10px; padding: 1px 7px;
      border-radius: 20px; margin-left: 6px; vertical-align: middle;
    }
    .variant-card ol { padding-left: 18px; color: #94afc7; font-size: 13.5px; }
    .variant-card ol li { margin-bottom: 5px; }
    .variant-card ol li code {
      background: rgba(0,0,0,.35); border: 1px solid rgba(255,255,255,.1);
      border-radius: 5px; padding: 1px 6px;
      font-family: 'Consolas', monospace; font-size: 12px; color: #7dd3fc;
    }

    .fields-table { width: 100%; border-collapse: collapse; margin-top: 4px; }
    .fields-table th, .fields-table td { text-align: left; padding: 9px 12px; font-size: 13.5px; }
    .fields-table th { color: #7a9bbf; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,.08); }
    .fields-table td { color: #b0c8de; border-bottom: 1px solid rgba(255,255,255,.04); }
    .fields-table tr:last-child td { border-bottom: none; }
    .fields-table td code {
      background: rgba(0,0,0,.35); border: 1px solid rgba(255,255,255,.1);
      border-radius: 5px; padding: 1px 7px;
      font-family: 'Consolas', monospace; font-size: 12.5px; color: #7dd3fc;
    }
    .fields-table td.field-name { color: #c9dff0; font-weight: 500; }

    hr { border: none; border-top: 1px solid rgba(255,255,255,.07); margin: 6px 0 20px; }

    footer {
      margin-top: 40px; padding: 28px 32px;
      background: rgba(0,0,0,.25);
      border-top: 1px solid rgba(255,255,255,.07);
      text-align: center;
    }
    footer .logo { font-size: 20px; font-weight: 700; color: #e8f4fd; letter-spacing: .5px; margin-bottom: 6px; }
    footer .version { font-size: 12px; color: #4a7a9b; margin-bottom: 14px; }
    footer .links { display: flex; justify-content: center; gap: 20px; flex-wrap: wrap; }
    footer .links a {
      color: #4aa8d8; text-decoration: none; font-size: 13.5px;
      display: flex; align-items: center; gap: 6px;
      padding: 5px 14px;
      border: 1px solid rgba(74,168,216,.25); border-radius: 20px;
      transition: all .2s;
    }
    footer .links a:hover {
      background: rgba(74,168,216,.12); border-color: rgba(74,168,216,.55); color: #7dd3fc;
    }
    footer .copy { margin-top: 16px; font-size: 12px; color: #3a5a74; }
  </style>
</head>
<body>

<div class="wrapper">

  <div class="page-header">
    <span class="tg-icon">&#9992;&#65039;</span>
    <h1>Подключение Telegram-уведомлений</h1>
    <p>Пошаговая инструкция</p>
  </div>

  <div class="card">
    <h2>&#128272; Шаг 1 &mdash; Создание бота в Telegram</h2>

    <div class="step">
      <div class="step-num">1</div>
      <div class="step-body">
        <strong>Откройте Telegram и найдите бота <code>@BotFather</code></strong>
        <p>Это официальный бот Telegram для создания и управления другими ботами.</p>
      </div>
    </div>

    <div class="step">
      <div class="step-num">2</div>
      <div class="step-body">
        <strong>Отправьте команду <code>/newbot</code></strong>
        <p>BotFather попросит придумать название бота (например, <em>«Мой Парсер»</em>) и уникальное имя (должно оканчиваться на <code>bot</code>, например, <em>«myparser_bot»</em>).</p>
      </div>
    </div>

    <div class="step">
      <div class="step-num">3</div>
      <div class="step-body">
        <strong>Скопируйте токен бота</strong>
        <p>После создания BotFather пришлёт сообщение с токеном вида:</p>
        <code class="url-code">123456789:AABBccDDeeFFggHHiiJJkkLLmmNNoo</code>
      </div>
    </div>
    <div class="callout callout-warn" style="margin-top:14px;">
      <span class="icon">&#9888;&#65039;</span>
      <span><strong>Важно:</strong> Токен — это пароль вашего бота. Не передавайте его посторонним. Поле в программе скрывает символы для безопасности.</span>
    </div>
  </div>

  <div class="card">
    <h2>&#128257; Шаг 2 &mdash; Выберите, куда бот будет отправлять сообщения</h2>
    <p style="color:#94afc7; margin-bottom:16px;">Бот не принимает сообщения &mdash; он только <strong style="color:#e8f4fd;">отправляет</strong>. Вы указываете <em>chat_id</em> &mdash; куда именно.</p>

    <div style="display:flex; flex-direction:column; gap:12px;">

      <div class="variant-card">
        <h3>&#128100; Вариант А &nbsp; <span class="badge">Проще</span></h3>
        <p style="color:#7a9bbf; font-size:13px; margin-bottom:10px;">Уведомления приходят вам в личку от вашего бота</p>
        <ol>
          <li>Найдите своего бота в Telegram по имени</li>
          <li>Нажмите <code>/start</code></li>
          <li>Откройте в браузере: <code>api.telegram.org/bot<em>ВАШ_ТОКЕН</em>/getUpdates</code></li>
          <li>В ответе найдите <code>"id"</code> внутри <code>"chat"</code> &mdash; это ваш <code>chat_id</code></li>
        </ol>
      </div>

      <div class="variant-card">
        <h3>&#128101; Вариант Б</h3>
        <p style="color:#7a9bbf; font-size:13px; margin-bottom:10px;">Бот пишет в группу или канал</p>
        <ol>
          <li>Добавьте бота в группу/канал как администратора</li>
          <li>Отправьте любое сообщение в эту группу</li>
          <li>Откройте: <code>api.telegram.org/bot<em>ВАШ_ТОКЕН</em>/getUpdates</code></li>
          <li>Найдите <code>"id"</code> внутри <code>"chat"</code> &mdash; для групп это <em>отрицательное</em> число</li>
        </ol>
        <p style="color:#7a9bbf; font-size:12.5px; margin-top:10px;">&#128161; Для публичных групп вместо числового ID можно ввести <code>@username</code>.</p>
      </div>

      <div class="variant-card">
        <h3>&#128268; Вариант В</h3>
        <p style="color:#7a9bbf; font-size:13px; margin-bottom:10px;">Бот пишет в конкретную ветку группы с включёнными темами (Topics / Форум)</p>
        <ol>
          <li>Добавьте бота в группу как администратора и включите Topics: Настройки &rarr; <em>Manage Group</em> &rarr; <em>Topics</em></li>
          <li>Напишите сообщение <strong>внутри нужной темы</strong>, затем откройте: <code>api.telegram.org/bot<em>ВАШ_ТОКЕН</em>/getUpdates</code></li>
          <li>Найдите поле <code>"message_thread_id"</code> &mdash; это Thread ID ветки. Введите его в поле <em>Thread ID (Topics)</em> в программе</li>
          <li>Если поле Thread ID оставить пустым &mdash; сообщения попадут в тему <em>General</em></li>
        </ol>
        <p style="color:#7a9bbf; font-size:12.5px; margin-top:10px;">&#128161; Один бот &mdash; несколько скриптов: каждый скрипт указывает свой Thread ID, чтобы уведомления не смешивались.</p>
      </div>

    </div>
  </div>

  <div class="card">
    <h2>&#9881;&#65039; Шаг 3 &mdash; Ввести данные в программу</h2>

    <table class="fields-table">
      <thead>
        <tr><th>Поле</th><th>Что вводить</th><th>Пример</th></tr>
      </thead>
      <tbody>
        <tr>
          <td class="field-name">Токен бота</td>
          <td>Токен от BotFather</td>
          <td><code>123456789:AABBcc&hellip;</code></td>
        </tr>
        <tr>
          <td class="field-name">ID чата/группы</td>
          <td>Числовой ID или @username</td>
          <td><code>-1001234567890</code> или <code>@mygroup</code></td>
        </tr>
        <tr>
          <td class="field-name">Thread ID (Topics)</td>
          <td>ID ветки внутри группы с Topics. <em>Необязательно</em> — оставьте пустым, если группа без тем или нужен General</td>
          <td><code>16</code></td>
        </tr>
      </tbody>
    </table>

    <hr />

    <p style="color:#94afc7; font-size:13.5px; margin-bottom:10px;"><strong style="color:#c9dff0;">Уведомлять о:</strong> &nbsp; выберите, какие события вас интересуют:</p>
    <ul style="color:#94afc7; font-size:13.5px; padding-left:20px;">
      <li><strong style="color:#c9dff0;">Остатке прокси</strong> &mdash; предупреждение когда рабочих прокси осталось &le;&nbsp;5</li>
      <li><strong style="color:#c9dff0;">Результате парсинга</strong> &mdash; краткая статистика после каждого cron-запуска</li>
      <li><strong style="color:#c9dff0;">Ошибках</strong> &mdash; критические сбои (прокси кончились, файл не найден и т.д.)</li>
    </ul>

    <div class="callout callout-tip" style="margin-top:14px;">
      <span class="icon">&#10003;</span>
      <span>После ввода токена и ID нажмите кнопку <strong>Тест</strong> &mdash; бот должен прислать тестовое сообщение. Если сообщение пришло, всё настроено правильно.</span>
    </div>
  </div>

  <div class="card">
    <h2>&#128683; Частые ошибки</h2>

    <div class="callout callout-warn" style="margin-bottom:10px;">
      <span class="icon">&#9888;&#65039;</span>
      <div>
        <strong>Сообщение не доходит</strong><br>
        <span>Убедитесь, что вы написали боту <code>/start</code> до того, как программа отправила первое сообщение. Боты Telegram не могут писать пользователю первыми, пока тот не инициировал диалог.</span>
      </div>
    </div>

    <div class="callout callout-warn" style="margin-bottom:10px;">
      <span class="icon">&#9888;&#65039;</span>
      <div>
        <strong>Бот не пишет в группу</strong><br>
        <span>Проверьте, что бот добавлен в группу и у него есть право отправлять сообщения. Для закрытых групп нужен числовой <code>chat_id</code>, @username не подойдёт.</span>
      </div>
    </div>

    <div class="callout callout-warn" style="margin-bottom:10px;">
      <span class="icon">&#9888;&#65039;</span>
      <div>
        <strong>getUpdates возвращает пустой список</strong><br>
        <span>Напишите боту любое сообщение в Telegram, затем снова откройте <code>getUpdates</code> в браузере &mdash; появится запись с <code>chat_id</code>.</span>
      </div>
    </div>

    <div class="callout callout-warn">
      <span class="icon">&#9888;&#65039;</span>
      <div>
        <strong>Сообщение уходит в General вместо нужной ветки</strong><br>
        <span>Укажите <code>Thread ID</code> нужной темы в поле настроек. Если поле пустое, а группа использует Topics &mdash; сообщения попадут в <em>General</em>. При ошибке доставки программа покажет подсказку в логах.</span>
      </div>
    </div>
  </div>

</div>

<footer>
  <div class="links">
    <a href="{{APP_SITE_URL}}" target="_blank">&#127760; Сайт автора</a>
    <a href="{{APP_TELEGRAM_URL}}" target="_blank">&#9992;&#65039; Telegram автора</a>
  </div>
  <div class="copy">&copy; 2025&ndash;2026 {{APP_DEVELOPER}}. Все права защищены.</div>
</footer>

</body>
</html>
"""
