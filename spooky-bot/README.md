# 🎃 Halloween Discord Bot (discord.py 2.x)

Starten:
1. pip install -r requirements.txt
2. cp .env.example .env (Token eintragen)
3. python bot.py

Fly.io 24/7:
fly launch --no-deploy
fly volumes create halloween_data --size 1
fly secrets set DISCORD_TOKEN="dein_token"
fly deploy
