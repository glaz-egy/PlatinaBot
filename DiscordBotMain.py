# -*- coding: utf-8 -*-

from random import random, randint
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from configparser import ConfigParser
import discord
import hashlib
import asyncio
import time
import sys
import os


class LogControl:
    def __init__(self, FileName):
        self.Name = FileName
    
    async def Log(self, WriteText, write_type='a'):
        with open(self.Name, write_type) as f:
            f.write(datetime.now().strftime('[%Y/%m/%d %H:%M:%S]')+'[Bot Log] '+WriteText+'\n')
    
    async def ErrorLog(self, WriteText, write_type='a'):
        with open(self.Name, write_type) as f:
            f.write(datetime.now().strftime('[%Y/%m/%d %H:%M:%S]')+'[Error Log] '+WriteText+'\n')
    
    async def MusicLog(self, WriteText, write_type='a'):
        with open(self.Name, write_type) as f:
            f.write(datetime.now().strftime('[%Y/%m/%d %H:%M:%S]')+'[Music Log] '+WriteText+'\n')

class VoiceEntry:
    def __init__(self, message, player):
        self.requester = message.author
        self.channel = message.channel
        self.player = player

    def __str__(self):
        fmt = '{} uploaded by {}: `{}`'.format(self.player.title, self.player.uploader, self.player.url)
        return fmt

class VoiceState:
    def __init__(self, bot):
        self.current = None
        self.voice = None
        self.bot = bot
        self.play_next_song = asyncio.Event()
        self.songs = asyncio.Queue()
        self.skip_votes = set() # a set of user_ids that voted
        self.audio_player = self.bot.loop.create_task(self.audio_player_task())

    def is_playing(self):
        if self.voice is None or self.current is None:
            return False

        player = self.current.player
        return not player.is_done()

    @property
    def player(self):
        return self.current.player

    def skip(self):
        self.skip_votes.clear()
        if self.is_playing():
            self.player.stop()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

    async def audio_player_task(self):
        while True:
            self.play_next_song.clear()
            self.current = await self.songs.get()
            await NextSet(MusicMessage)
            await self.bot.send_message(self.current.channel, 'Now playing **{}**'.format(self.current))
            self.current.player.start()
            await self.play_next_song.wait()

class MusicPlayer:
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, server):
        state = self.voice_states.get(server.id)
        if state is None:
            state = VoiceState(self.bot)
            self.voice_states[server.id] = state

        return state

    async def play(self, message, *, song : str):
        state = self.get_voice_state(message.server)
        opts = {
            'default_search': 'auto',
            'quiet': True,
        }

        if state.voice is None:
            voice_channel = message.author.voice_channel
            if voice_channel is None:
                await self.bot.send_message(message.channel, 'ボイスチャネルに入ってないじゃん!')
                await log.ErrorLog('User not in voice channel')
                return False
            state.voice = await self.bot.join_voice_channel(voice_channel)

        try:
            player = await state.voice.create_ytdl_player(song, ytdl_options=opts, after=state.toggle_next)
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            await self.bot.send_message(message.channel, fmt.format(type(e).__name__, e))
        else:
            player.volume = 0.3
            entry = VoiceEntry(message, player)
            await log.MusicLog('{}: {}'.format(player.title, player.url))
            await state.songs.put(entry)

    async def pause(self, message):
        state = self.get_voice_state(message.server)
        if state.is_playing():
            player = state.player
            player.pause()

    async def resume(self, message):
        state = self.get_voice_state(message.server)
        if state.is_playing():
            player = state.player
            player.resume()

    async def stop(self, message):
        server = message.server
        state = self.get_voice_state(server)

        if state.current.player.is_playing():
            player = state.current.player
            player.stop()

        try:
            state.audio_player.cancel()
            del self.voice_states[server.id]
            await state.voice.disconnect()
        except:
            pass

    async def skip(self, message):
        state = self.get_voice_state(message.server)
        if not state.is_playing():
            await self.bot.send_message(message.channel, 'Not playing any music right now...')
            return

        state.skip()

MusicMessage = None
player = None
PlayURL = []
NextList = []
NowPlay = 0
RandomFlag = False
PauseFlag = False
PlayFlag = False
version = 'version: 1.3.0'
log = LogControl('bot.log')
config = ConfigParser()
if os.path.isfile('config.ini'):
    config.read('config.ini')
else:
    log.ErrorLog('Config file not exist')
    sys.exit(1)
token = config['BOTDATA']['token']
prefix = config['BOTDATA']['cmdprefix']
if len(PlayURL) == 0:
    if os.path.isfile('playlist.txt'):
        with open('playlist.txt', 'r') as f:
            temp = f.readlines()
        for play in temp:
            PlayURL.append(play.replace('\n', ''))
    else:
        with open('playlist.txt', 'w') as f:
            pass

PlayURLs = deepcopy(PlayURL)

client = discord.Client()

CommandDict = OrderedDict()
CommandDict = {'`'+prefix+'role`': '役職関係のコマンド 詳しくは`{}help roleを見てね！`'.format(prefix),
                '`'+prefix+'play`': '音楽を再生するかもしれないコマンド `{}help play`で詳しく確認できるよ！'.format(prefix),
                '`'+prefix+'version`': '現在のバージョンを確認できる',
                '`'+prefix+'help`' : '今見てるのに説明いる？　ヘルプ用なんだけど'}

PlayCmdDict = OrderedDict()
PlayCmdDict = {'`'+prefix+'play [-r] [$url] [--list]`': '音楽を再生します　`-r`を付けるとランダム再生 `$[url]`でurlを優先再生 `--list`でプレイリストを確認',
                '`'+prefix+'next`': '次の音楽を再生します',
                '`'+prefix+'stop`': '音楽の再生をストップ＆ボイスチャネルから抜ける',
                '`'+prefix+'pause`': '音楽の再生をストップ　次再生は続きから',
                '`'+prefix+'addmusic url [url]...`': '音楽をプレイリストに追加',
                '`'+prefix+'delmusic url [url]...`': 'プレイリストから削除',
                '`'+prefix+'musiclist`': 'プレイリストを確認(廃止予定)'}

RoleCmdDict = OrderedDict()
RoleCmdDict = {'`'+prefix+'role option`': '`!role`はオプションを必ず付けてね！',
                '`--list`': '現在ある役職を確認できます',
                '`--create [RoleName]`': '役職を新しく作れます',
                '`--remove [RoleName]`': '役職を消せます',
                '`--add [RoleName]`': '自分に役職を追加します',
                '`--del [RoleName]`': '自分の役職を消します',}

async def NextSet(message):
    global NowPlay
    global player
    global PlayURLs
    if not RandomFlag: NowPlay = 0
    else: NowPlay = randint(0, len(PlayURLs)-1)
    await player.play(message, song='https://www.youtube.com/watch?v='+PlayURLs[NowPlay])
    await log.MusicLog('Set {}'.format(PlayURLs[NowPlay]))
    PlayURLs.remove(PlayURLs[NowPlay])
    if len(PlayURLs) == 0:
        PlayURLs = deepcopy(PlayURL)

async def ListOut(message):
    await log.Log('Call playlist is {}'.format(PlayURL))
    for url in PlayURL:
        await client.send_message(message.channel, '`https://www.youtube.com/watch?v={}`\n'.format(url))

@client.event
async def on_ready():
    await log.Log('Bot is Logging in!!')

@client.event
async def on_message(message):
    global MusicMessage
    global player
    global NowPlay
    global PlayURL
    global PlayURLs
    global RandomFlag
    global PauseFlag
    global PlayFlag
    if message.content.startswith(prefix+'role'):
        DelFlag = False
        AddFlag = False
        CmdFlag = False
        CreateFlag = False
        RemoveFlag = False
        cmd = message.content.split()
        if '--list' in cmd:
            CmdFlag = True
            RoleList = message.server.roles
            for Role in RoleList:
                if not '@everyone' == Role.name:
                    await client.send_message(message.channel, '`{}`'.format(Role.name))
            await log.Log('Confirmation role list')
            return
        if '--del' in cmd:
            CmdFlag = True
            DelFlag = True
            RoleName = cmd[cmd.index('--del')+1]
        if '--add' in cmd:
            CmdFlag = True
            AddFlag = True
            RoleName = cmd[cmd.index('--add')+1]
        if '--create' in cmd:
            CmdFlag = True
            CreateFlag = True
            RoleName = cmd[cmd.index('--create')+1]
        if '--remove' in cmd:
            CmdFlag = True
            RemoveFlag = True
            RoleName = cmd[cmd.index('--remove')+1]
        if not CmdFlag:
            if len(cmd) > 1:
                await client.send_message(message.channel, 'オプションが間違っている気がするなぁ')
                await log.ErrorLog('The option is incorrect error')
                return
            await client.send_message(message.channel, '`!role`だけじゃ何したいのか分からないんだけど')
            await log.ErrorLog('no option error')
            return

        if (CreateFlag or RemoveFlag) and (AddFlag or DelFlag):
            await client.send_message(message.channel, 'そのコマンドは両立出来ないなぁ')
            await log.ErrorLog('A command for the server and a command for the member are entered error')
        if CreateFlag and RemoveFlag:
            await client.send_message(message.channel, '作るのと削除と、どっちが良いの!？')
            await log.ErrorLog('Create and Remove command are entered error')
            return
        elif CreateFlag:
            role = discord.utils.get(message.author.server.roles, name=RoleName)
            if role == None:
                await client.create_role(message.server, name=RoleName, colour=discord.Colour(randint(0, 16777215)))
                await log.Log('Create role: {}'.format(RoleName))
            else:
                await client.send_message(message.channel, 'あるよ！ {} あるよッ！'.format(RoleName))
                await log.Log('Role: {} is exist in this server yet'.format(RoleName))
            return
        elif RemoveFlag:
            role = discord.utils.get(message.author.server.roles, name=RoleName)
            await client.delete_role(message.server, role)
            await log.Log('Remove role: {}'.format(RoleName))
            return

        if AddFlag and DelFlag:
            await client.send_message(message.channel, '追加するの？　消すの？　はっきりしてよ……')
            await log.ErrorLog('Add and Del command are entered')
            return
        role = discord.utils.get(message.author.server.roles, name=RoleName)
        if role is None:
            await client.send_message(message.channel, 'そんな役職無いよ!')
            await log.ErrorLog('Role: {} is not exist in this server'.format(RoleName))
            return
        elif AddFlag:
            await client.add_roles(message.author, role)
            await log.Log('Add role: {} in {}'.format(message.author.name, RoleName))
        elif DelFlag:
            await client.remove_roles(message.author, role)
            await log.Log('Del role: {}\'s {}'.format(message.author.name, RoleName))

    if message.content.startswith(prefix+'play'):
        urlUseFlag = False
        cmd = message.content.split()
        if '--list' in cmd:
            await ListOut(message)
            return
        if '-r' in cmd: RandomFlag = True
        else: RandomFlag = False
        if len(cmd) >= 2:
            for cmdpar in cmd:
                if '$' in cmdpar:
                    urlUseFlag = True
                    url = cmdpar.replace('$', '')
        MusicMessage = message
        if PauseFlag:
            await player.resume(message)
        else:
            music = randint(0, len(PlayURLs)-1)
            try:
                player = MusicPlayer(client)
                await player.play(message, song=('https://www.youtube.com/watch?v='+PlayURLs[music if RandomFlag else 0] if not urlUseFlag else url))
                if not urlUseFlag: PlayURLs.remove(PlayURLs[music if RandomFlag else 0])
                NowPlay = music if RandomFlag else 0
                PlayFlag = True
            except discord.errors.InvalidArgument:
                pass
            except:
                await log.ErrorLog('Already Music playing')
                await client.send_message(message.channel, 'Already Music playing')
            

    if message.content.startswith(prefix+'next'):
        await log.MusicLog('Music skip')
        await player.skip(message)

    if message.content.startswith(prefix+'stop'):
        await log.MusicLog('Music stop')
        await player.stop(message)
        PlayFlag = False
        player = None
        PlayURLs = deepcopy(PlayURL)
        
    if message.content.startswith(prefix+'addmusic'):
        links = message.content.split()[1:]
        for link in links:
            link = link.replace('https://www.youtube.com/watch?v=', '')
            link = link.replace('https://youtu.be/', '')
            if not link in PlayURL:
                PlayURL.append(link)
                PlayURLs.append(link)
                await log.MusicLog('Add {}'.format(link))
                await client.send_message(message.channel, '{} が欲しかった！'.format('https://www.youtube.com/watch?v='+link))
                with open('playlist.txt', 'a') as f:
                    f.write('{}\n'.format(link))
            else:
                await log.MusicLog('Music Overlap {}'.format(link))
                await client.send_message(message.channel, 'その曲もう入ってない？')
    
    if message.content.startswith(prefix+'musiclist'):
        await ListOut(message)
    
    if message.content.startswith(prefix+'pause'):
        await log.MusicLog('Music pause')
        await player.pause(message)
        PauseFlag = True
        PlayFlag = False
    
    if message.content.startswith('!delmusic'):
        links = message.content.split()[1:]
        for link in links:
            link = link.replace('https://www.youtube.com/watch?v=', '')
            link = link.replace('https://youtu.be/', '')
            try:
                PlayURL.remove(link)
                try:
                    PlayURLs.remove(link)
                except:
                    pass
                await log.MusicLog('Del {}'.format(link))
                await client.send_message(message.channel, '{} なんてもういらないよね！'.format('https://www.youtube.com/watch?v='+link))
                with open('playlist.txt', 'w') as f:
                    for URL in PlayURL:
                        f.write('{}\n'.format(URL))
            except:
                await log.ErrorLog('{} not exist list'.format(link))
                await client.send_message(message.channel, 'そんな曲入ってたかな？')
        

    if message.content.startswith(prefix+'version'):
        await log.Log(version)
        await client.send_message(message.channel, version)

    if message.content.startswith(prefix+'help'):
        cmds = message.content.split()
        if len(cmds) > 1:
            for cmd in cmds:
                if cmd == 'play':
                    for key, value in PlayCmdDict.items():
                        await client.send_message(message.channel, '{}: {}'.format(key, value))
                if cmd == 'role':
                    for key, value in RoleCmdDict.items():
                        await client.send_message(message.channel, '{}: {}'.format(key, value))
        else:
            for key, value in CommandDict.items():
                await client.send_message(message.channel, '{}: {}'.format(key, value))

    
    if message.content.startswith(prefix+'exit'):
        PassWord = message.content.split()[1]
        HashWord = hashlib.sha256(PassWord.encode('utf-8')).hexdigest()
        if HashWord == config['ADMINDATA']['passhash']:
            await log.Log('Bot exit')
            await sys.exit(0)

@client.event
async def on_member_join(member):
    channel = client.get_channel(config['BOTDATA']['mainch'])
    readme = client.get_channel(config['BOTDATA']['readmech'])
    rand = random()
    if rand <= 0.25:
        await client.send_message(channel, 'いらっしゃい **{}** さん、良ければ {} を見てくださいね'.format(member.name, readme.name))
    elif rand <= 0.5:
        await client.send_message(channel, 'ようこそ **{}** お兄ちゃん、{} を見て欲しいな 可愛い妹からのお願いだよ'.format(member.name, readme.name))
    elif rand <= 0.75:
        await client.send_message(channel, '{} は読むべきだと思うな **{}** さん'.format(readme.name, member.name))
    else:
        await client.send_message(channel, 'なぜ {} を読まないんだ **{}** 説明書を読まないと分からないことも有るだろ'.format(readme.name, member.name))
    print('Join {}'.format(member.name))


client.run(token)