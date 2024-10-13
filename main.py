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
from urllib.parse import urlparse
import aiohttp
import discord
import redis.asyncio as redis
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse

USER_BASE = 'https://www.roblox.com/users/'
THUMBNAIL_BASE = 'https://thumbnails.roblox.com/v1/users/avatar?&size=720x720&format=Png&userIds='

REDIS_CACHE_KEY = 'embed_cache'
REDIS_LOCK_KEY = 'webhook_lock'

# Lifespan to attach .session attribute, cancel + shutdown is for local testing
@contextlib.asynccontextmanager
async def lifespan(a):
  a.session = aiohttp.ClientSession()
  a.webhook = discord.Webhook.from_url(os.getenv('url'), session = a.session)

  if app.test:
    redis_url = 'redis://localhost:6379?decode_responses=True'
  else:
    redis_url = os.getenv('KV_URL')
  a.redis = await redis.from_url(redis_url)

  a.lock = a.redis.lock(REDIS_LOCK_KEY, timeout = 10)
  try:
    yield
  except asyncio.CancelledError:
    print('Ignoring cancelled error. (CTRL+C)')
  await a.session.close()

app = Starlette(lifespan = lifespan)
app.test = os.getenv('test')
app.started_at = datetime.datetime.now()

@app.route('/', methods = ['GET'])
async def root(request):
  return PlainTextResponse(status_code = 200)

async def send(embeds):
  embeds = [discord.Embed.from_dict(json.loads(i)) for i in embeds]
  print('sending', len(embeds))
  for i, embed in enumerate(embeds):
    embed.url += '?' + str(i) # prevent embeds merging
  await app.webhook.send(embeds = embeds)
  await app.redis.ltrim(REDIS_CACHE_KEY, len(embeds), -1)
  print('sent', len(embeds), 'remaining', await app.redis.llen(REDIS_CACHE_KEY))

async def queue(embed):
  await app.redis.rpush(REDIS_CACHE_KEY, json.dumps(embed.to_dict()))

  # supports a rate of at most about ~10 joinleave/sec = maybe 5k concurrent players?
  # more than 50embeds/5s would require multiple webhooks
  # if it doesn't finish the first time, the next request will do it
  # to avoid 504 resends and getting duplicates, we gotta return 200 within 10 seconds
  # ensures at least 2 seconds worth of stacked embeds
  await asyncio.sleep(2)

  if await app.lock.acquire(blocking_timeout = 7):
    try:
      while embeds := await app.redis.lrange(REDIS_CACHE_KEY, 0, 9):
        await send(embeds) # send in chunks of 10
    finally:
      await app.lock.release()
  else:
    print('acquire timed out')

def format_seconds(seconds):
  minutes, seconds = divmod(seconds, 60)
  if minutes > 0:
    return '{}min, {}s'.format(minutes, seconds)
  return '{}s'.format(seconds)

@app.route('/log', methods = ['POST'])
async def log(request):
  print('start:', app.started_at)
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
    url = USER_BASE + str(data['userId']),
    title = data['username'] + ' ' + action + ' | SPC: ' + str(data['playerCount']),
    color = color
  )
  for name, value in fields:
    embed.add_field(name = name, value = value, inline = True)
  embed.set_footer(text = str(datetime.datetime.fromtimestamp(data['now'] / 1000))[:-3])
  embed.set_author(name = data['serverType'] + ' ' + data['serverId'])

  async with app.session.get(THUMBNAIL_BASE + str(data['userId'])) as resp:
    if resp.status == 200:
      result = await resp.json()
      if result['data']:
        embed.set_thumbnail(url = result['data'][0]['imageUrl'])

  await queue(embed)

  return PlainTextResponse(status_code = 200)
