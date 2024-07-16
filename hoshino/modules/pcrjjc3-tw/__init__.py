from json import load, dump
from nonebot import get_bot, on_command, CommandSession
from hoshino import priv
from hoshino.typing import NoticeSession, MessageSegment, CQEvent
from .pcrclient import pcrclient, ApiException, get_headers
from asyncio import Lock
from os.path import dirname, join, exists
from copy import deepcopy
from traceback import format_exc
from .safeservice import SafeService
from .playerpref import decryptxml
from .create_img import generate_info_pic, generate_support_pic, _get_cx_name
from hoshino.util import pic2b64
from .jjchistory import *
from hoshino.util import FreqLimiter
from .pcrjjc import *

'''
轮询时的post改为协程并发，再次大幅加速，batch_size=4，为测试服务器相对较优的参数，
测试服务器单post收发延迟为500ms，自己服务器的较优参数请自行测试

'''
sv_help = '''
注意：数字2为服务器编号，仅支持2~4服

[竞技场bind 10位uid] 默认双场均启用，排名下降时推送 也可使用[竞技场bind 2 9位uid]
[竞技场查询 10位uid] 查询（bind后无需输入2 uid，可缩写为jjccx、看看） 也可使用[竞技场bind 2 9位uid]
[停止竞技场bind] 停止jjc推送
[停止公主竞技场bind] 停止pjjc推送
[启用竞技场bind] 启用jjc推送
[启用公主竞技场bind] 启用pjjc推送
[竞技场历史] jjc变化记录（bind开启有效，可保留10条）
[公主竞技场历史] pjjc变化记录（bind开启有效，可保留10条）
[详细查询 10位uid] 能不用就不用（bind后无需输入2 uid） 也可使用[详细查询 2 9位uid]
[竞技场关注 10位uid] 默认双场均启用，排名变化及上线时推送 也可使用[竞技场关注 2 9位uid]
[删除竞技场bind] 删除bind
[删除关注 x] 删除第x个关注
[竞技场bind状态] 查看排名变动推送bind状态
[关注列表] 返回关注的序号以及对应的游戏UID
[关注查询 x] 查询第x个关注 可缩写为看看

'''.strip()

# 限制查询的频率
lmt = FreqLimiter(2)

# 用于暂停周期扫描的变量
pause = 0

sv = SafeService('jjc_tw', help_=sv_help, bundle='pcr查询')


@sv.on_fullmatch('竞技场帮助', only_to_me=False)
async def send_jjchelp(bot, ev):
    await bot.send(ev, f'{sv_help}')


@sv.on_fullmatch('查询竞技场bind数', only_to_me=False)
async def pcrjjc_number(bot, ev):
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, '抱歉，您的权限不足，只有bot主人才能进行该操作！')
        return
    
    n = pcrjjc.pcrjjc_number()
    await bot.send(ev, f'当前竞技场已bind的账号数量为【{n}】个')


@sv.on_rex('(暂停|开启)扫描', only_to_me=False)
async def pcrjjc_pause(bot, ev):
    global pause
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, '抱歉，您的权限不足，只有bot主人才能进行该操作！')
        return
    if ev['match'].group(1) == '开启':
        pause = 0
        await bot.send(ev, '已开启扫描')
        return
    else:
        pause = 1
        await bot.send(ev, '已暂停扫描')
        return


@sv.on_rex(r'^竞技场bind\s*(\d)\s*(\d{9})$')  # 支持匹配空格，空格可有可无且长度无限制
async def on_arena_bind(bot, ev):
    cx = ev['match'].group(1)
    id = ev['match'].group(2)
    
    # qq号
    uid = str(ev['user_id'])
    gid = str(ev['group_id'])
    
    res, err = await pcrjjc.bind(cx, id, uid, gid)
    
    if err != None:
        await bot.finish(ev, err)

    await bot.finish(ev, res, at_sender=True)


# uid是qq id才是游戏uid
@sv.on_rex(r'^竞技场关注\s*(\d)\s*(\d{9})$')  # 支持匹配空格，空格可有可无且长度无限制
async def on_arena_observer(bot, ev):
    uid = str(ev['user_id'])
    id = ev['match'].group(2)
    cx = ev['match'].group(1)
    gid = str(ev['group_id'])
    
    msg, err = await pcrjjc.add_observer(cx, id, uid, gid)

    if err is not None:
        await bot.finish(ev, err, at_sender=True)
    
    await bot.finish(ev, msg, at_sender=True)


@sv.on_rex(r'^(竞技场查询|jjccx|看看|关注查询)\s*(\d)?\s*(\d{9})?$')
async def on_query_arena(bot, ev):
    global binds, lck, observer

    robj = ev['match']
    cx = robj.group(2)
    id = robj.group(3)
    uid = str(ev['user_id'])
    
    # at玩家会发生什么事情
    if id is None and cx is None:
        for message in ev.message:
            if message.type == 'at':
                uid = str(message.data['qq'])
            
    if not lmt.check(uid):
        await bot.finish(ev, '您查询得过于频繁，请稍等片刻', at_sender=True)
    lmt.start_cd(uid)
    
    res, err = await pcrjjc.user_query(cx, id, uid)
    
    if err is not None:
        await bot.finish(ev, err, at_sender=True)
    else:
        await bot.finish(ev, res, at_sender=False)


@sv.on_prefix('竞技场历史')
async def send_arena_history(bot, ev):
    # 竞技场历史记录
    await bot.finish(ev, pcrjjc.arena_history(), at_sender=True)


@sv.on_prefix('公主竞技场历史')
async def send_parena_history(bot, ev):
    await bot.finish(ev, pcrjjc.parena_history(), at_sender=True)


@sv.on_fullmatch('关注列表')
async def send_observer_list(bot, ev):
    uid = str(ev['user_id'])
   
    msg = await pcrjjc.observer_list(uid)
    await bot.send(ev, msg, at_sender=True)


# @sv.on_rex(r'^详细查询\s*(\d)?\s*(\d{9})?$')
# async def on_query_arena_all(bot, ev):
#     global binds, lck
#     robj = ev['match']
#     cx = robj.group(1)
#     id = robj.group(2)
#     uid = str(ev['user_id'])

#     async with lck:
#         if id is None and cx is None:
#             # at群友会发生什么事情
#             for message in ev.message:
#                 if message.type == 'at':
#                     uid = str(message.data['qq'])
#                 if uid not in binds:
#                     await bot.finish(ev, '该群友还未bind竞技场', at_sender=True)
#                     return

#             if uid not in binds:
#                 await bot.finish(ev, '您还未bind竞技场', at_sender=True)
#                 return
#             else:
#                 id = binds[uid]['id']
#                 cx = binds[uid]['cx']
#         try:
#             res = await pcrjjc.query(cx, id)
#             if res == 'lack shareprefs':
#                 await bot.finish(ev, f'查询出错，缺少该服的配置文件', at_sender=True)
#                 return
#             sv.logger.info('开始生成竞技场查询图片...')  # 通过log显示信息
#             result_image = await generate_info_pic(res, cx, uid)
#             sv.logger.info('获取到图片信息...')  # 通过log显示信息
#             result_image = pic2b64(result_image)  # 转base64发送，不用将图片存本地
#             result_image = MessageSegment.image(result_image)
#             result_support = await generate_support_pic(res, uid)
#             result_support = pic2b64(result_support)  # 转base64发送，不用将图片存本地
#             result_support = MessageSegment.image(result_support)
#             sv.logger.info('竞技场查询图片已准备完毕！')
#             try:
#                 await bot.finish(ev, f"\n{str(result_image)}\n{result_support}", at_sender=True)
#                 # await bot.finish(ev, f"\n{str(result_image)}", at_sender=True)
#             except Exception:
#                 sv.logger.info("do nothing")
#         except ApiException:
#             await bot.finish(ev, f'查询出错，API出错', at_sender=True)
#         except aiohttp.ClientProxyConnectionError:
#             await bot.finish(ev, f'查询出错，连接代理失败，请再次尝试', at_sender=True)
#         except Exception as e:
#             await bot.finish(ev, f'查询出错，{e}', at_sender=True)


@sv.on_rex('(启用|停止)(公主)?竞技场bind')
async def change_arena_sub(bot, ev):
    if_grand =  ev['match'].group(2) is not None
    uid = str(ev['user_id'])
    if_open = ev['match'].group(1) == '启用'

    msg = await pcrjjc.arena_sub(if_grand, if_open, uid)
    await bot.finish(ev, msg, at_sender=True)


# 需要优化 使用QQ号和at应该都要生效
@sv.on_prefix('删除竞技场bind')
async def delete_arena_sub(bot, ev):
    uid = str(ev['user_id'])

    for message in ev.message:
        if message.type == 'at':
            if not priv.check_priv(ev, priv.SUPERUSER):
                await bot.finish(ev, '删除他人bind请联系维护', at_sender=True)
                return
            uid = str(message.data['qq'])
        
    msg = await pcrjjc.delete_sub(uid)

    await bot.finish(ev, msg, at_sender=True)


# 删除整个群的账号
@sv.on_rex(r'^清理账号\s*(\d*)?$')
async def delete_group(bot, ev):
    global binds, lck, olck, observer
    if not priv.check_priv(ev, priv.SUPERUSER):
        return
    robj = ev['match']
    gid = str(robj.group(1))
    # 获取全部要读取的uid

    await pcrjjc.clear_group(gid)

    await bot.finish(ev, '已删除该群的所有账号', at_sender=True)
    

@sv.on_rex(r'^删除关注\s*(\d*)?$')
async def delete_observer_arena(bot, ev):
    global olck, observer
    uid = str(ev['user_id'])
    robj = ev['match']
    num = int(robj.group(1))

    msg = pcrjjc.delete_observer(uid, num)
    
    await bot.finish(ev, msg, at_sender=True)


# @sv.on_fullmatch('竞技场bind状态')
# async def send_arena_sub_status(bot, ev):
#     global binds, lck
#     uid = str(ev['user_id'])

#     if uid not in binds:
#         await bot.send(ev, '您还未bind竞技场', at_sender=True)
#     else:
#         info = binds[uid]
#         await bot.finish(ev,
#                          f'''
#     当前竞技场bindID：{info['id']}
#     竞技场bind：{'开启' if info['arena_on'] else '关闭'}
#     公主竞技场bind：{'开启' if info['grand_arena_on'] else '关闭'}''', at_sender=True)


@sv.on_prefix('更新版本')
async def updateVersion(bot, ev: CQEvent):
    global header_path, default_headers
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, '抱歉，您的权限不足，只有bot主人才能进行该操作！')
        return
    version = ev.message.extract_plain_text()
    msg = pcrjjc.updateVersion(version)
    
    await bot.finish(ev, msg, at_sender=True)

bot = get_bot()

async def callback(gid, uid, msg):
    global bot
    await bot.send_group_msg(
            group_id=int(gid),
            message=f'[CQ:at,qq={uid}]{msg}')


@sv.scheduled_job('interval', seconds=40)
async def on_arena_schedule():
    # 估计语法糖里有time操作，所以不能用time来读取时间
    if pause == 1:
        return

    await pcrjjc.getAllInfo(callback)


@sv.on_notice('group_decrease.leave')
async def leave_notice(session: NoticeSession):
    uid = str(session.ctx['user_id'])
    gid = str(session.ctx['group_id'])
    
    msg = pcrjjc.deleteUser(uid, gid)
    if msg is not None:
        bot = get_bot()
        await bot.send_group_msg(
                    group_id=int(gid),
                    message=msg
                )


@sv.on_notice('group_decrease.kick')
async def kick_notice(session: NoticeSession):
    global lck, binds, olck
    uid = str(session.ctx['user_id'])
    gid = str(session.ctx['group_id'])
    
    msg = pcrjjc.deleteUser(uid, gid)
    if msg is not None:
        bot = get_bot()
        await bot.send_group_msg(
                    group_id=int(gid),
                    message=msg
                )
