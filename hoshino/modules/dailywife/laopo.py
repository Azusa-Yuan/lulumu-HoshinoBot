import time

from hoshino import Service
from hoshino.typing import CQEvent
import httpx
import hashlib
import base64
import os
import json
import datetime
from random import choice
import random
from asyncio import Lock
import asyncio
import yaml

lck = Lock()

sv = Service(
    name="dailywife",  # 功能名
    visible=True,  # 可见性
    enable_on_default=True,  # 默认启用
    bundle="娱乐",  # 分组归类
    help_="发送【今日老婆】随机抓取群友作为老婆",  # 帮助说明

)

husband = {}
special = {}
cfgpath = os.path.join(os.path.dirname(__file__), 'config.yaml')
if os.path.exists(cfgpath):
    with open(cfgpath, 'r', encoding='utf-8') as f:
        husband = yaml.load(f, Loader=yaml.SafeLoader)

sppath = os.path.join(os.path.dirname(__file__), 'config.json')
if os.path.exists(sppath):
    with open(sppath) as f:
        special = json.load(f)

time_interval = 60 * 60 * 24 * 30


def get_pig_list(all_list):
    now = int(time.time())
    id_list = []
    for member_list in all_list:
        if (now - member_list['last_sent_time']) < time_interval:
            id_list.append(member_list['user_id'])
    return id_list


def get_member_list(all_list):
    id_list = []
    for member_list in all_list:
        id_list.append(member_list['user_id'])
    return id_list


async def download_avatar(user_id: str) -> bytes:
    url = f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
    data = await download_url(url)
    if not data or hashlib.md5(data).hexdigest() == "acef72340ac0e914090bd35799f5594e":
        url = f"http://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100"
        data = await download_url(url)
    return data


async def download_url(url: str) -> bytes:
    async with httpx.AsyncClient() as client:
        for i in range(3):
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                return resp.content
            except Exception as e:
                print(f"Error downloading {url}, retry {i}/3: {str(e)}")


async def get_wife_info(member_info, qqid):
    img = await download_avatar(qqid)
    base64_str = base64.b64encode(img).decode()
    avatar = 'base64://' + base64_str
    member_name = (member_info["card"] or member_info["nickname"])
    result = f'''\n你今天的群友老婆是:
[CQ:image,file={avatar}]
{member_name}({qqid})'''
    return result


async def get_husband_info(member_info, qqid):
    img = await download_avatar(qqid)
    base64_str = base64.b64encode(img).decode()
    avatar = 'base64://' + base64_str
    member_name = (member_info["card"] or member_info["nickname"])
    result = f'''\n你每天的群友老公是:
[CQ:image,file={avatar}]
{member_name}({qqid})'''
    return result


async def get_pig_info(member_info, qqid, k):
    img = await download_avatar(qqid)
    base64_str = base64.b64encode(img).decode()
    avatar = 'base64://' + base64_str
    member_name = (member_info["card"] or member_info["nickname"])
    result = f'''\n今日的{k}号猪头群友是:
[CQ:image,file={avatar}]
{member_name}({qqid})'''
    return result


def load_group_config(group_id: str):
    filename = os.path.join(os.path.dirname(__file__), 'config', f'{group_id}.json')
    try:
        with open(filename, encoding='utf8') as f:
            config = json.load(f)
            return config
    except:
        return None


def load_pig_config():
    filename = os.path.join(os.path.dirname(__file__), f'pig.json')
    try:
        with open(filename, encoding='utf8') as f:
            config = json.load(f)
            return config
    except:
        return None


def write_pig_config(group_id: str, pig_id, date: str, config):
    filename = os.path.join(os.path.dirname(__file__), f'pig.json')
    if config == None:
        config = {}

    config[group_id] = {
        "date": date,
        "pig_id": pig_id,
    }
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False)


def write_group_config(group_id: str, link_id: str, wife_id: str, date: str, config):
    config_file = os.path.join(os.path.dirname(__file__), 'config', f'{group_id}.json')
    if config != None:
        config[link_id] = [wife_id, date]
    else:
        config = {link_id: [wife_id, date]}
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False)


@sv.on_fullmatch('今日老婆')
async def dailywife(bot, ev: CQEvent):
    global lck, special
    groupid = ev.group_id
    user_id = ev.user_id
    bot_id = ev.self_id
    wife_id = None
    today = str(datetime.date.today())
    async with lck:
        config = load_group_config(str(groupid))
        random = True

        if config != None:
            if str(user_id) in list(config):
                if config[str(user_id)][1] == today:
                    wife_id = config[str(user_id)][0]
                else:
                    del config[str(user_id)]

        if wife_id is None:
            all_list = await bot.get_group_member_list(group_id=groupid)
            id_list = get_member_list(all_list)
            if config != None:
                for record_id in list(config):
                    if config[record_id][1] != today:
                        del config[record_id]
                    else:
                        # bad
                        try:
                            id_list.remove(int(config[record_id][0]))
                        except:
                            del config[record_id]

            special_list = list(special.keys())
            if str(user_id) in special_list:
                if groupid in special[str(user_id)]["groupid"]:
                    index = special[str(user_id)]["groupid"].index(groupid)
                    wife_id = special[str(user_id)]["wife_id"][index]
                    random = False

            if random:
                for special_id in special:
                    if groupid in special[special_id]["groupid"]:
                        index = special[special_id]["groupid"].index(groupid)
                        special_wife = special[special_id]["wife_id"][index]
                        if special_wife in id_list:
                            id_list.remove(special_wife)

                # id_list.remove(bot_id)
                if user_id in id_list:
                    id_list.remove(user_id)
                wife_id = choice(id_list)

        write_group_config(groupid, user_id, wife_id, today, config)
        member_info = await bot.get_group_member_info(group_id=groupid, user_id=wife_id)
        result = await get_wife_info(member_info, wife_id)
        await bot.send(ev, result, at_sender=True)
        await asyncio.sleep(0.1)


@sv.on_fullmatch('今日老公')
async def dailyhusband(bot, ev: CQEvent):
    if husband is None:
        return

    if random.random() < 0.6:
        return 0
    husband_id = husband["husband"]
    groupid = ev.group_id
    member_info = await bot.get_group_member_info(group_id=groupid, user_id=husband_id)
    result = await get_husband_info(member_info, husband_id)
    await bot.send(ev, result, at_sender=True)


@sv.on_fullmatch('今日猪头')
async def dailyhusband(bot, ev: CQEvent):
    today = str(datetime.date.today())
    groupid = ev.group_id

    config = load_pig_config()
    if_exist = 0
    if config != None:
        if str(groupid) in config:
            if config[str(groupid)]["date"] == today:
                if_exist = 1

    if if_exist == 0:
        all_list = await bot.get_group_member_list(group_id=groupid)
        pig_list = get_pig_list(all_list)
        # print(pig_list)
        pig_num = len(pig_list) // 20 + 1
        # sample 返回长度为k的列表
        # print(pig_num)
        pig_list = random.sample(pig_list, k=int(pig_num))
        write_pig_config(groupid, pig_list, today, config)
        config = load_pig_config()

    length = len(config[str(groupid)]["pig_id"])
    k = random.randint(0, length - 1)
    pig_id = config[str(groupid)]["pig_id"][k]

    member_info = await bot.get_group_member_info(group_id=groupid, user_id=pig_id)
    result = await get_pig_info(member_info, pig_id, k)
    await bot.send(ev, result, at_sender=True)

if __name__ == '__main__':
    pass
