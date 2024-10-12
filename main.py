import os
import json

# Load configs for local hosting
path = 'config.json'
if os.path.isfile(path): # <-- file won't exist in production
  with open(path) as f: 
    config = json.loads(f.read())
  for key, value in config.items():
    os.environ[key] = value
  os.environ['test'] = '1'

# Use alternate api
from discord.http import Route
Route.BASE = 'https://discordapp.com/api/v9' # < 10

import asyncio
import datetime
import contextlib
import aiohttp
import discord
from fastapi import FastAPI, Request

webhook_url = os.getenv('url')

user_base = 'https://www.roblox.com/users/'
thumbnail_base = 'https://thumbnails.roblox.com/v1/users/avatar?&size=720x720&format=Png&userIds='

# Lifespan to attach .session attribute, cancel + shutdown is for local testing
@contextlib.asynccontextmanager
async def lifespan(a):
  a.session = aiohttp.ClientSession()
  a.webhook = discord.Webhook.from_url(webhook_url, session = a.session)
  try:
    yield
  except asyncio.CancelledError:
    print('Ignoring cancelled error. (CTRL+C)')
  await a.session.close()
  
app = FastAPI(lifespan = lifespan)

@app.get('/')
async def root():
  return True

cache = []
lock = asyncio.Lock()
async def queue(embed):
  cache.append(embed)

  # 5 second delay to ensure at least 5 seconds worth of stacked embeds
  # supports a rate of at most about ~10 joinleave/sec = maybe 5k concurrent players?
  # more than 50embeds/5s would require multiple webhooks
  await asyncio.sleep(5)

  async with lock:
    print('got lock! this is cache', cache)
    if cache: # still has items
      embeds_chunks = []
      embeds = []
      for i in list(cache):
        embeds.append(i)
        cache.remove(i)
        if len(embeds) == 10:
          embeds_chunks.append(embeds)
          embeds = []
      if embeds:
        embeds_chunks.append(embeds)
      for embeds in embeds_chunks:
        for i, embed in enumerate(embeds):
          embed.url += '?' + str(i) # prevent embeds merging
        await app.webhook.send(embeds = embeds)

def format_seconds(seconds):
  minutes, seconds = divmod(seconds, 60)
  if minutes > 0:
    return '{}min, {}s'.format(minutes, seconds)
  return '{}s'.format(seconds)

@app.post('/log')
async def log(request : Request):
  data = await request.json()
  print(json.dumps(data, indent = 4))

  if seconds := data.get('totalSeconds'):
    action = 'Left'
    color = discord.Color.red()
    fields = [
      ('Total Seconds', format_seconds(seconds)),
      ('Used Feature', str(data['usedFeature'])),
      ('Server Age', format_seconds(data['serverAge']))
    ]
  else:
    action = 'Joined'
    color = discord.Color.green()
    fields = [
      ('Account Age', str(data['userAge']) + ' days'),
      ('Locale', data['userLocale']),
      ('Country', str(data['userCountry'])),
      ('Ping', str(data['userPing'])),
      ('Premium', str(data['userPremium'])),
      ('Server Age', format_seconds(data['serverAge']))
    ]

  embed = discord.Embed(
    url = user_base + str(data['userId']),
    title = data['username'] + ' ' + action + ' | SPC: ' + str(data['playerCount']),
    color = color
  )
  for name, value in fields:
    embed.add_field(name = name, value = value, inline = True)
  embed.set_footer(text = str(datetime.datetime.now()))
  embed.set_author(name = data['serverType'] + ' ' + data['serverId'])

  async with app.session.get(thumbnail_base + str(data['userId'])) as resp:
    if resp.status == 200:
      result = await resp.json()
      if result['data']:
        embed.set_thumbnail(url = (respData)['data'][0]['imageUrl'])

  asyncio.create_task(queue(embed)) # custom vercel runtime required if we do this

  return 200
