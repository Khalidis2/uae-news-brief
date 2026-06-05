# Cloud deployment with GitHub Actions

This makes the UAE daily brief run in the cloud even when your PC is off.

GitHub Actions will:

- Run every day at 08:00 UAE time.
- Generate the PDF from Google News RSS.
- Send the dated PDF to Telegram.
- Keep the bot token in GitHub Secrets, not in the code.

## 1. Create a GitHub repository

Create a new GitHub repository, for example:

```text
uae-news-brief
```

Private is fine. Public also works, but private is better for your bot project.

## 2. Upload this project to GitHub

From PowerShell:

```powershell
cd "C:\Users\aaldh\OneDrive\Desktop\news sum"
git init
git add .
git commit -m "Add UAE daily news brief cloud workflow"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/uae-news-brief.git
git push -u origin main
```

Replace `YOUR_GITHUB_USERNAME` with your GitHub username.

## 3. Add Telegram secrets in GitHub

Open the repository on GitHub, then go to:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

Create these two secrets:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Use your BotFather token for `TELEGRAM_BOT_TOKEN`.

Use this for `TELEGRAM_CHAT_ID`:

```text
47329648
```

Do not put the bot token in any Python file.

## 4. Test it now

Open the repository on GitHub:

```text
Actions -> UAE Daily Brief Telegram -> Run workflow
```

If it succeeds, Telegram should receive the PDF.

## 5. Automatic daily run

The workflow file is:

```text
.github/workflows/uae-daily-brief.yml
```

It runs daily with this schedule:

```yaml
cron: "0 4 * * *"
```

That is 04:00 UTC, which is 08:00 in the UAE.

## Notes

- Your PC can be off.
- Internet is provided by GitHub's runner.
- No OpenAI API or paid news API is used.
- GitHub Actions scheduled runs can be delayed by a few minutes.
- If Telegram does not receive the file, check the failed run under the GitHub Actions tab.
