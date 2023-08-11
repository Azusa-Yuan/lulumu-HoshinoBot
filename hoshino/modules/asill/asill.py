import random, os, json
from hoshino import Service, R, aiorequests
from hoshino.typing import CQEvent, Message
from hoshino.util import FreqLimiter
from nonebot.permission import SUPERUSER
import hoshino
from hoshino import priv
import difflib

sv = Service('asill', enable_on_default=True, visible=True,help_='''
[发病 对象] 对发病对象发病
[小作文] 随机发送一篇发病小作文
[病情加重 对象/小作文] 将一篇发病小作文添加到数据库中（必须带“/”）
[病情查重 小作文] 对一篇小作文进行查重
[<回复一个小作文> 病情查重] 同上
'''.strip())


def get_data():
    _path = os.path.join(os.path.dirname(__file__), 'data.json')
    if os.path.exists(_path):
        with open(_path, "r", encoding='utf-8') as df:
            try:
                words = json.load(df)
            except Exception as e:
                hoshino.logger.error(f'读取发病小作文时发生错误{type(e)}')
                return None
    return words


word_list = get_data()
lmt = FreqLimiter(14400)

# 可在此配置要进行发病限制的群
group_list = {"852670048"}


@sv.on_fullmatch('重载小作文')
async def reload(bot, ev: CQEvent):
    global word_list
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, '抱歉，您的权限不足，只有bot主人才能进行该操作！')
        return
    word_list = get_data()
    await bot.send(ev, '重载成功')


@sv.on_fullmatch(('asill帮助', '发病帮助', '小作文帮助', '帮助发病', '小作文发病'))
async def asill_help(bot, ev: CQEvent):
    await bot.send(ev, f"{sv.help}")


@sv.on_fullmatch('小作文')
async def xzw(bot, ev: CQEvent):
    global word_list
    illness = random.choice(word_list)
    await bot.send(ev, illness["text"])


@sv.on_prefix('发病')
async def fb(bot, ev: CQEvent):
    aim = str(ev.message).strip()
    if str(ev['group_id']) in group_list:
        uid = str(ev['user_id'])
        if not lmt.check(uid):
            left_time = int(lmt.left_time(uid)/60)
            await bot.finish(ev, f'您发病过于频繁，请等待{left_time}分钟', at_sender=True)
        lmt.start_cd(uid)

    if not aim:
        await bot.send(ev, "请发送[发病 对象]~", at_sender=True)
    else:
        global word_list
        illness = random.choice(word_list)
        text = illness["text"]
        person = illness["person"]
        text = text.replace(person,aim)
        await bot.send(ev, text)


@sv.on_prefix('病情加重')
async def bqjz(bot, ev: CQEvent):
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, '抱歉，您的权限不足，只有bot主人才能进行该操作！')
        return
    kw = ev.message.extract_plain_text().strip()
    arr = kw.split('/')
    if not arr[0] or not arr[1] or len(arr) > 2:
        await bot.send(ev, "请发送[病情加重 对象/小作文]（必须带“/”）~", at_sender=True)
    else:
        global word_list
        new_illness = {"person" : arr[0], "text" : arr[1]}
        _path = os.path.join(os.path.dirname(__file__), 'data.json')
        if os.path.exists(_path):
            word_list.append(new_illness)
            with open(_path,"w",encoding='utf8') as df:        
                try:
                    json.dump(word_list,df,indent=4)
                    await bot.send(ev, "病情已添加", at_sender=True)
                except Exception as e:
                    hoshino.logger.error(f'添加发病小作文时发生错误{type(e)}')
                    return None
        else:
            hoshino.logger.error(f'目录下未找到发病小作文')


# 字符串之间相似度
def string_similar(s1, s2):
    return difflib.SequenceMatcher(None, s1, s2).quick_ratio()


async def check(bot, ev: CQEvent, text):
    global word_list
    for data in word_list:
        text2 = data["text"]
        rate = string_similar(text2, text)
        if rate > 0.6:
            msg = f'在本文库中，总文字复制比：{rate:.2%}\n相似小作文：\n{text2}'
            await bot.send(ev, msg)
            return
    msg = '文库内没有相似的小作文'
    await bot.send(ev, msg)


@sv.on_prefix('病情查重')
async def chachong(bot, ev: CQEvent):
    kw = ev.message.extract_plain_text().strip()
    await check(bot, ev, kw)


@sv.on_message()
async def huifuchachong(bot, ev: CQEvent):
    if len(ev.message) <= 0:
        return
    fseg = ev.message[0]
    if fseg.type == 'reply' and ev.message.extract_plain_text().strip() == '病情查重':
        msg = await bot.get_msg(message_id=fseg.data['id'])
        text = Message(msg['message']).extract_plain_text().strip()
        await check(bot, ev, text)
