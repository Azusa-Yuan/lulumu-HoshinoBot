from datetime import datetime, timedelta

from nonebot import get_bot

from hoshino import Service, log, priv
from hoshino.typing import CQEvent
from hoshino.util import DailyNumberLimiter
from hoshino.config import NICKNAME

from hoshino.config.picfinder import threshold, SAUCENAO_KEY, SEARCH_TIMEOUT, CHAIN_REPLY, DAILY_LIMIT, helptext, CHECK, enableguild, IGNORE_STAMP

if type(NICKNAME) == str:
    NICKNAME = [NICKNAME]

sv = Service('picfinder', help_=helptext)
from .image import get_image_data_sauce, get_image_data_ascii, check_screenshot

lmtd = DailyNumberLimiter(DAILY_LIMIT)
logger = sv.logger


class PicListener:
    def __init__(self):
        self.on = {}
        self.count = {}
        self.limit = {}
        self.timeout = {}

    def get_on_off_status(self, gid):
        return self.on[gid] if self.on.get(gid) is not None else False

    def turn_on(self, gid, uid):
        self.on[gid] = uid
        self.timeout[gid] = datetime.now()+timedelta(seconds=SEARCH_TIMEOUT)
        self.count[gid] = 0
        self.limit[gid] = DAILY_LIMIT-lmtd.get_num(uid)

    def turn_off(self, gid):
        self.on.pop(gid)
        self.count.pop(gid)
        self.timeout.pop(gid)
        self.limit.pop(gid)

    def count_plus(self, gid):
        self.count[gid] += 1


pls = PicListener()

bot = get_bot()
@bot.on_message('private')
async def picprivite(ctx: CQEvent):

    flag = 1
    for pfcmd in ['识图', '搜图', '查图', '找图']:
        if pfcmd in str(ctx['message']):
            flag = 0

    if flag:
        return

    type = ctx["sub_type"]
    sid = int(ctx["self_id"])
    uid = int(ctx["sender"]["user_id"])
    gid = 0
    if priv.check_block_user(uid):
        return
    ret = None
    for m in ctx.message:
        if m.type == 'image':
            file = m.data['file']
            url = m.data['url']
            ret = 1
    if 'c2cpicdw.qpic.cn/offpic_new/' in url:
        md5 = file[:-6].upper()
        url = f"http://gchat.qpic.cn/gchatpic_new/0/0-0-{md5}/0?term=2"
    if type == "group":
        return
    await bot.send_msg(self_id=sid, user_id=uid, group_id=gid, message='正在搜索，请稍候～')
    result = await get_image_data_sauce(url, SAUCENAO_KEY)
    image_data_report = result[0]
    simimax = result[1]
    if 'Index #' in image_data_report:
        await bot.send_private_msg(self_id=sid, user_id=bot.config.SUPERUSERS[0], message='发生index解析错误')
        await bot.send_private_msg(self_id=sid, user_id=bot.config.SUPERUSERS[0], message=url)
        await bot.send_private_msg(self_id=sid, user_id=bot.config.SUPERUSERS[0], message=image_data_report)
    await bot.send_msg(self_id=sid, user_id=uid, group_id=gid, message=image_data_report)

    if float(simimax) < float(threshold):
        if simimax != 0:
            await bot.send_msg(self_id=sid, user_id=uid, group_id=gid, message="相似度过低，换用ascii2d检索中…")
        else:
            logger.error("SauceNao not found imageInfo")
            await bot.send_msg(self_id=sid, user_id=uid, group_id=gid, message='SauceNao检索失败,换用ascii2d检索中…')

        image_data_report = await get_image_data_ascii(url)
        if image_data_report[0]:
            await bot.send_msg(self_id=sid, user_id=uid, group_id=gid, message=image_data_report[0])
        if image_data_report[1]:
            await bot.send_msg(self_id=sid, user_id=uid, group_id=gid, message=image_data_report[1])
        if not (image_data_report[0] or image_data_report[1]):
            logger.error("ascii2d not found imageInfo")
            await bot.send_msg(self_id=sid, user_id=uid, group_id=gid, message='ascii2d检索失败…')


