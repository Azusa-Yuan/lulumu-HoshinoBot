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
import time
import requests
import json
from .jjchistory import *
from hoshino.util import FreqLimiter
import asyncio
# 减少warning
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
'''
version：轮询时的post改为协程并发，再次大幅加速，batch_size=4，为测试服务器相对较优的参数，
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
# 启动时的两个文件，不存在就创建
# headers文件
header_path = os.path.join(os.path.dirname(__file__), 'headers.json')
if not os.path.exists(header_path):
    default_headers = get_headers()
    with open(header_path, 'w', encoding='UTF-8') as f:
        json.dump(default_headers, f, indent=4, ensure_ascii=False)

# 用于暂停周期扫描的变量
pause = 0
# 头像框设置文件，默认彩色
current_dir = os.path.join(os.path.dirname(__file__), 'frame.json')
if not os.path.exists(current_dir):
    data = {
        "customize": {},
        "default_frame": "color.png"

    }
    with open(current_dir, 'w', encoding='UTF-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

sv = SafeService('jjc_tw', help_=sv_help, bundle='pcr查询')


@sv.on_fullmatch('竞技场帮助', only_to_me=False)
async def send_jjchelp(bot, ev):
    await bot.send(ev, f'{sv_help}')


# 读取bind和关注配置
curpath = dirname(__file__)
config = join(curpath, 'binds.json')
config_2 = join(curpath, 'observer.json')
root = {
    'arena_bind': {}
}
root_2 = {
    'arena_observer': {}
}

if exists(config):
    with open(config) as fp:
        root = load(fp)

if exists(config_2):
    with open(config_2) as fp:
        root_2 = load(fp)
binds = root['arena_bind']
observer = root_2['arena_observer']

# 读取代理配置
with open(join(curpath, 'account.json')) as fp:
    pinfo = load(fp)

# 一些变量初始化
cache = {}
cache_2 = {}  # 专用于关注使用
cache_time = {}  # 专用于关注使用
cache_introduction = {}  # 专用于关注使用
client = None

# 设置异步锁保证线程安全
lck = Lock()
captcha_lck = Lock()
qlck = Lock()
olck = Lock()

# 数据库对象初始化
JJCH = JJCHistoryStorage()


# 查询配置文件是否存在
def judge_file(cx):
    cx_path = os.path.join(os.path.dirname(__file__), f'{cx}cx_tw.sonet.princessconnect.v2.playerprefs.xml')
    if os.path.exists(cx_path):
        return True
    else:
        return False


# 获取配置文件
def get_client():
    acinfo_1cx = decryptxml(join(curpath, '1cx_tw.sonet.princessconnect.v2.playerprefs.xml')) if judge_file(1) else {
        'admin': ''}
    client_1cx = pcrclient(acinfo_1cx['UDID'], acinfo_1cx['SHORT_UDID_lowBits'], acinfo_1cx['VIEWER_ID_lowBits'],
                           acinfo_1cx['TW_SERVER_ID'], pinfo['proxy']) if judge_file(1) else None

    # 判断2~4服客户端所用账号的服务器号
    cx5 = 0
    if judge_file(2):
        cx5 = 2
    elif judge_file(3):
        cx5 = 3
    elif judge_file(4):
        cx5 = 4

    if cx5 == 0:
        acinfo_2cx = {'admin': ''}
        client_2cx = None
    else:
        # 2~4服统一为client_2cx
        acinfo_2cx = decryptxml(join(curpath, str(cx5) + 'cx_tw.sonet.princessconnect.v2.playerprefs.xml'))
        client_2cx = pcrclient(acinfo_2cx['UDID'], acinfo_2cx['SHORT_UDID_lowBits'], acinfo_2cx['VIEWER_ID_lowBits'],
                               acinfo_2cx['TW_SERVER_ID'], pinfo['proxy'])

    return client_1cx, client_2cx, acinfo_1cx, acinfo_2cx


client_1cx, client_2cx, acinfo_1cx, acinfo_2cx = get_client()

# 变为登录状态
loop = asyncio.get_event_loop()
if client_1cx is not None:
    loop.run_until_complete(loop.create_task(client_1cx.login()))
if client_2cx is not None:
    loop.run_until_complete(loop.create_task(client_2cx.login()))


async def query(cx: str, id: str):
    global client_1cx, client_2cx
    if cx == '1':
        client = client_1cx
    elif cx == '2' or cx == '3' or cx == '4':
        client = client_2cx
    else:
        client = None
    if client is None:
        return 'lack shareprefs'
    async with qlck:
        try:
            res = (await client.callapi('/profile/get_profile', {
                'target_viewer_id': int(cx + id)
            }))
        except Exception as e:
            await client.login()
            res = (await client.callapi('/profile/get_profile', {
                'target_viewer_id': int(cx + id)
            }))
        return res


async def query_single(cx: str, id: str, delay: float):
    global client_1cx, client_2cx
    if cx == '1':
        client = client_1cx
    elif cx == '2' or cx == '3' or cx == '4':
        client = client_2cx
    else:
        client = None
    if client is None:
        return 'lack shareprefs'

    try:
        res = await client.callapi('/profile/get_profile', {
            'target_viewer_id': int(cx + id)
        }, delay=delay)
    except Exception as e:
        # 发生错误返回空
        try:
            await client.login()
            res = (await client.callapi('/profile/get_profile', {
                'target_viewer_id': int(cx + id)
            }))
        except Exception as e:
            res = None
    return res


# 并发进行，batch_size 为并发数
async def query_batch(cx_list: list, id_list: list, batch_size: int = 5, time_interval: float = 50):
    all_reslut = []
    all_uid = []
    lenth = int(len(cx_list))
    for i in range(int(lenth / batch_size) + 1):
        cx_batch = cx_list[i * batch_size: (i + 1) * batch_size]
        id_batch = id_list[i * batch_size: (i + 1) * batch_size]
        tasks = []
        if len(cx_batch) == 0:
            continue
        for j in range(len(cx_batch)):
            tasks.append(asyncio.create_task(query_single(cx_batch[j], id_batch[j], time_interval * j)))
        async with qlck:
            await asyncio.wait(tasks)
        for j in range(len(cx_batch)):
            singe_reslut = tasks[j].result()
            all_reslut.append(singe_reslut)
            # all_uid 记录所有uid，可以通过index方法找到uid的下标,发生错误时则记录空值
            if singe_reslut:
                all_uid.append(singe_reslut['user_info']['viewer_id'])
            else:
                all_uid.append(singe_reslut)
    return all_reslut, all_uid


# 并发进行，list内容一次性全部并发
async def query_all(cx_list: list, id_list: list, time_interval: float = 50):
    all_reslut = []
    all_uid = []
    tasks = []
    lenth = int(len(cx_list))
    for i in range(lenth):
        tasks.append(asyncio.create_task(query_single(cx_list[i], id_list[i], time_interval * i)))
    async with qlck:
        await asyncio.wait(tasks)
    for i in range(lenth):
        singe_reslut = tasks[i].result()
        all_reslut.append(singe_reslut)
        all_uid.append(singe_reslut['user_info']['viewer_id'])
    return all_reslut, all_uid


def save_binds():
    with open(config, 'w') as fp:
        dump(root, fp, indent=4)


def save_observer():
    with open(config_2, 'w') as fp:
        dump(root_2, fp, indent=4)


@sv.on_fullmatch('查询竞技场bind数', only_to_me=False)
async def pcrjjc_number(bot, ev):
    global binds, lck
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, '抱歉，您的权限不足，只有bot主人才能进行该操作！')
        return
    async with lck:
        await bot.send(ev, f'当前竞技场已bind的账号数量为【{len(cache) + len(cache_2)}】个')


@sv.on_rex('(暂停|开启)扫描', only_to_me=False)
async def pcrjjc_pause(bot, ev):
    global binds, lck, pause
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
    global binds, lck

    if ev['match'].group(1) not in ['1', '2', '3', '4']:
        await bot.send(ev, '服务器选择错误！')
        return
    if ev['match'].group(1) == '1':
        if client_1cx is None:
            await bot.send(ev, '服务器选择错误！支持的服务器有2/3/4')
            return
    elif client_2cx is None:
        await bot.send(ev, '服务器选择错误！支持的服务器有1')
        return

    async with lck:
        uid = str(ev['user_id'])
        last = binds[uid] if uid in binds else None
        cx = ev['match'].group(1)
        binds[uid] = {
            'cx': cx,
            'id': ev['match'].group(2),
            'uid': uid,
            'gid': str(ev['group_id']),
            'arena_on': last is None or last['arena_on'],
            'grand_arena_on': last is None or last['grand_arena_on'],
        }
        save_binds()
        msg = '竞技场bind成功'

    await bot.finish(ev, msg, at_sender=True)


# uid是qq id才是游戏uid
@sv.on_rex(r'^竞技场关注\s*(\d)\s*(\d{9})$')  # 支持匹配空格，空格可有可无且长度无限制
async def on_arena_observer(bot, ev):
    global binds, olck, observer

    if ev['match'].group(1) not in ['1', '2', '3', '4']:
        await bot.send(ev, '服务器选择错误！')
        return
    if ev['match'].group(1) == '1':
        if client_1cx is None:
            await bot.send(ev, '服务器选择错误！支持的服务器有2/3/4')
            return
    elif client_2cx is None:
        await bot.send(ev, '服务器选择错误！支持的服务器有1')
        return

    async with olck:
        uid = str(ev['user_id'])
        id = ev['match'].group(2)
        cx = ev['match'].group(1)
        if uid in observer:
            if len(observer[uid]['cx']) >= 4:
                msg = '因为服务器性能有限，仅支持关注四名'
                await bot.finish(ev, msg)
                return
            if id in observer[uid]['id']:
                msg = '您已关注该玩家'
                await bot.finish(ev, msg, at_sender=True)
                return
            observer[uid]['id'].append(id)
            observer[uid]['cx'].append(cx)
            observer[uid]['gid'].append(str(ev['group_id']))
        else:
            # 绑定的key是QQ号，关注的key是游戏uid
            observer[uid] = {
                'cx': [cx],
                'id': [id],
                'uid': uid,
                'gid': [str(ev['group_id'])],
            }
            # print(observer)
        save_observer()
        msg = '竞技场关注成功'

    await bot.finish(ev, msg, at_sender=True)


@sv.on_rex(r'^(竞技场查询|jjccx|看看|关注查询)\s*(\d)?\s*(\d{9})?$')
async def on_query_arena(bot, ev):
    global binds, lck, observer

    robj = ev['match']
    cx = robj.group(2)
    id = robj.group(3)
    uid = str(ev['user_id'])
    cx_name = _get_cx_name(cx)

    if not lmt.check(uid):
        await bot.finish(ev, '您查询得过于频繁，请稍等片刻', at_sender=True)
    lmt.start_cd(uid)

    async with lck:

        # 判断关注
        if id is None and cx:
            num = int(cx)
            if num == 0:
                await bot.finish(ev, '请输入正确的序号', at_sender=True)
                return
            if uid not in observer:
                await bot.finish(ev, '您还没有关注任何玩家', at_sender=True)
                return
            if int(num) > len(observer[uid]['cx']):
                await bot.finish(ev, '请输入正确的序号', at_sender=True)
                return
            num -= 1
            cx = observer[uid]['cx'][num]
            id = observer[uid]['id'][num]
            cx_name = _get_cx_name(cx)

        # 没有服务器和id的情况下
        if id is None and cx is None:
            # at玩家会发生什么事情
            for message in ev.message:
                if message.type == 'at':
                    uid = str(message.data['qq'])
                if uid not in binds:
                    await bot.finish(ev, '该群友还未bind竞技场', at_sender=True)
                    return

            if uid not in binds:
                await bot.finish(ev, '您还未bind竞技场', at_sender=True)
                return
            else:
                id = binds[uid]['id']
                cx = binds[uid]['cx']
                cx_name = _get_cx_name(cx)
        try:
            res = await query(cx, id)

            if res == 'lack shareprefs':
                await bot.finish(ev, f'查询出错，缺少该服的配置文件', at_sender=True)
                return
            last_login_time = int(res['user_info']['last_login_time'])
            last_login_date = time.localtime(last_login_time)
            last_login_str = time.strftime('%Y-%m-%d %H:%M:%S', last_login_date)

            await bot.send(ev,
                           f'''区服：{cx_name}
jjc排名：{res['user_info']["arena_rank"]}
pjjc排名：{res['user_info']["grand_arena_rank"]}
最后登录：{last_login_str}
竞技场场次：{res["user_info"]["arena_group"]}
公主竞技场场次：{res["user_info"]["grand_arena_group"]}''', at_sender=False)
        except ApiException as e:
            await bot.finish(ev, f'查询出错，{e}', at_sender=True)
        except requests.exceptions.ProxyError:
            await bot.finish(ev, f'查询出错，连接代理失败，请再次尝试', at_sender=True)
        except Exception as e:
            await bot.finish(ev, f'查询出错，{e}', at_sender=True)


@on_command('tmp看看')
async def _query(session: CommandSession):
    uid = str(session.ctx['user_id'])
    id = binds[uid]['id']
    cx = binds[uid]['cx']
    cx_name = _get_cx_name(cx)
    try:
        res = await query(cx, id)

        if res == 'lack shareprefs':
            await session.finish(f'查询出错，缺少该服的配置文件', at_sender=True)
            return
        last_login_time = int(res['user_info']['last_login_time'])
        last_login_date = time.localtime(last_login_time)
        last_login_str = time.strftime('%Y-%m-%d %H:%M:%S', last_login_date)

        await session.send(
            f'''区服：{cx_name}
昵称：{res['user_info']["user_name"]}
jjc排名：{res['user_info']["arena_rank"]}
pjjc排名：{res['user_info']["grand_arena_rank"]}
最后登录：{last_login_str}
竞技场场次：{res["user_info"]["arena_group"]}
公主竞技场场次：{res["user_info"]["grand_arena_group"]}''')
    except ApiException as e:
        await session.finish(f'查询出错，{e}')
    except requests.exceptions.ProxyError:
        await session.finish(f'查询出错，连接代理失败，请再次尝试')
    except Exception as e:
        await session.finish(f'查询出错，{e}')


@sv.on_prefix('竞技场历史')
async def send_arena_history(bot, ev):
    '''
    竞技场历史记录
    '''
    global binds, lck
    uid = str(ev['user_id'])
    if uid not in binds:
        await bot.send(ev, '未bind竞技场', at_sender=True)
    else:
        ID = binds[uid]['id']
        msg = f'\n{JJCH._select(ID, 1)}'
        await bot.finish(ev, msg, at_sender=True)


@sv.on_prefix('公主竞技场历史')
async def send_parena_history(bot, ev):
    global binds, lck
    uid = str(ev['user_id'])
    if uid not in binds:
        await bot.send(ev, '未bind竞技场', at_sender=True)
    else:
        ID = binds[uid]['id']
        msg = f'\n{JJCH._select(ID, 0)}'
        await bot.finish(ev, msg, at_sender=True)


@sv.on_fullmatch('关注列表')
async def creat_observer_list(bot, ev):
    global observer, cache
    uid = str(ev['user_id'])
    if uid not in observer:
        await bot.send(ev, '您没有关注任何玩家', at_sender=True)
        return
    observer_uid = observer[uid]['id']
    observer_cx = observer[uid]['cx']
    person_observer = [observer_cx[i] + observer_uid[i] for i in range(len(observer_uid))]
    msg = ''
    for pos, uid in enumerate(person_observer):
        msg += '\r\n'
        if int(uid) in cache:
            msg += f'{pos + 1}  {uid}  {cache[int(uid)][2]}  jjc:{cache[int(uid)][0]}  pjjc:{cache[int(uid)][1]}'
        else:
            msg += f'{pos + 1}  {uid}'
    msg += '\r\n'
    msg += '该排名有延时(最大为130s)，仅供参考'
    await bot.send(ev, msg, at_sender=True)


@sv.on_rex(r'^详细查询\s*(\d)?\s*(\d{9})?$')
async def on_query_arena_all(bot, ev):
    global binds, lck
    robj = ev['match']
    cx = robj.group(1)
    id = robj.group(2)
    uid = str(ev['user_id'])

    async with lck:
        if id == None and cx == None:
            # at群友会发生什么事情
            for message in ev.message:
                if message.type == 'at':
                    uid = str(message.data['qq'])
                if uid not in binds:
                    await bot.finish(ev, '该群友还未bind竞技场', at_sender=True)
                    return

            if not uid in binds:
                await bot.finish(ev, '您还未bind竞技场', at_sender=True)
                return
            else:
                id = binds[uid]['id']
                cx = binds[uid]['cx']
        try:
            res = await query(cx, id)
            if res == 'lack shareprefs':
                await bot.finish(ev, f'查询出错，缺少该服的配置文件', at_sender=True)
                return
            sv.logger.info('开始生成竞技场查询图片...')  # 通过log显示信息
            result_image = await generate_info_pic(res, cx, uid)
            sv.logger.info('获取到图片信息...')  # 通过log显示信息
            result_image = pic2b64(result_image)  # 转base64发送，不用将图片存本地
            result_image = MessageSegment.image(result_image)
            result_support = await generate_support_pic(res, uid)
            result_support = pic2b64(result_support)  # 转base64发送，不用将图片存本地
            result_support = MessageSegment.image(result_support)
            sv.logger.info('竞技场查询图片已准备完毕！')
            try:
                await bot.finish(ev, f"\n{str(result_image)}\n{result_support}", at_sender=True)
                # await bot.finish(ev, f"\n{str(result_image)}", at_sender=True)
            except Exception as e:
                sv.logger.info("do nothing")
        except ApiException as e:
            await bot.finish(ev, f'查询出错，API出错', at_sender=True)
        except requests.exceptions.ProxyError:
            await bot.finish(ev, f'查询出错，连接代理失败，请再次尝试', at_sender=True)
        except Exception as e:
            await bot.finish(ev, f'查询出错，{e}', at_sender=True)


@sv.on_rex('(启用|停止)(公主)?竞技场bind')
async def change_arena_sub(bot, ev):
    global binds, lck

    key = 'arena_on' if ev['match'].group(2) is None else 'grand_arena_on'
    uid = str(ev['user_id'])

    async with lck:
        if not uid in binds:
            await bot.send(ev, '您还未bind竞技场', at_sender=True)
        else:
            binds[uid][key] = ev['match'].group(1) == '启用'
            save_binds()
            await bot.finish(ev, f'{ev["match"].group(0)}成功', at_sender=True)


def delete_arena(uid):
    '''
    订阅删除方法
    '''
    JJCH._remove(binds[uid]['id'])
    binds.pop(uid)
    save_binds()


@sv.on_prefix('删除竞技场bind')
async def delete_arena_sub(bot, ev):
    global binds, lck

    uid = str(ev['user_id'])

    if ev.message[0].type == 'at':
        if not priv.check_priv(ev, priv.SUPERUSER):
            await bot.finish(ev, '删除他人bind请联系维护', at_sender=True)
            return
        uid = str(ev.message[0].data['qq'])
        if uid in observer:
            async with olck:
                delete_observer_all(uid)

    elif len(ev.message) == 1 and ev.message[0].type == 'text' and not ev.message[0].data['text']:
        uid = str(ev['user_id'])

    if not uid in binds:
        await bot.finish(ev, '未bind竞技场', at_sender=True)
        return

    async with lck:
        delete_arena(uid)

    await bot.finish(ev, '删除竞技场bind成功', at_sender=True)


@sv.on_rex(r'^删除bind\s*(\d*)?$')
async def delete_arena_sub(bot, ev):
    global binds, lck, olck
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.finish(ev, '删除他人bind请联系维护', at_sender=True)
        return
    robj = ev['match']
    uid = str(robj.group(1))

    if not uid in binds:
        await bot.finish(ev, '未bind竞技场', at_sender=True)

    async with lck:
        delete_arena(uid)

    if uid in observer:
        async with olck:
            delete_observer_all(uid)

    await bot.finish(ev, '删除竞技场bind成功', at_sender=True)


# 删除整个群的账号
@sv.on_rex(r'^清理账号\s*(\d*)?$')
async def delete_group(bot, ev):
    global binds, lck, olck, observer
    if not priv.check_priv(ev, priv.SUPERUSER):
        return
    robj = ev['match']
    gid = str(robj.group(1))
    # 获取全部要读取的uid

    async with lck:
        bind_cache = deepcopy(binds)
        for uid in bind_cache:
            info = bind_cache[uid]
            if gid == info['gid']:
                delete_arena(uid)

    async with olck:
        observer_cache = deepcopy(observer)
        for uid in observer_cache:
            info = observer_cache[uid]
            length = len(info['id'])
            for i in range(length):
                if gid == info['gid'][i]:
                    delete_observer(uid, i + 1)

    await bot.finish(ev, '已删除该群的所有账号', at_sender=True)


def delete_observer(uid, num):
    '''
    关注删除方法
    '''
    global binds, lck, observer
    lenth = len(observer[uid]['id'])
    if 0 < num <= lenth:
        del observer[uid]['id'][num - 1]
        del observer[uid]['cx'][num - 1]
        del observer[uid]['gid'][num - 1]
        save_observer()
        return 0
    return 1


def delete_observer_all(uid):
    observer.pop(uid)
    save_observer()


@sv.on_rex(r'^删除关注\s*(\d*)?$')
async def delete_observer_arena(bot, ev):
    global olck, observer
    uid = str(ev['user_id'])
    robj = ev['match']
    num = int(robj.group(1))

    if uid not in observer:
        await bot.finish(ev, '您还没有关注任何玩家', at_sender=True)
        return
    async with olck:
        result = delete_observer(uid, num)

    if result:
        await bot.finish(ev, '请输入正确的序号', at_sender=True)
        return
    await bot.finish(ev, '删除关注成功', at_sender=True)


@sv.on_fullmatch('竞技场bind状态')
async def send_arena_sub_status(bot, ev):
    global binds, lck
    uid = str(ev['user_id'])

    if not uid in binds:
        await bot.send(ev, '您还未bind竞技场', at_sender=True)
    else:
        info = binds[uid]
        await bot.finish(ev,
                         f'''
    当前竞技场bindID：{info['id']}
    竞技场bind：{'开启' if info['arena_on'] else '关闭'}
    公主竞技场bind：{'开启' if info['grand_arena_on'] else '关闭'}''', at_sender=True)


@sv.on_prefix('更新版本')
async def updateVersion(bot, ev: CQEvent):
    if not priv.check_priv(ev, priv.SUPERUSER):
        await bot.send(ev, '抱歉，您的权限不足，只有bot主人才能进行该操作！')
        return
    try:
        version = ev.message.extract_plain_text()
        if client_1cx is not None:
            await client_1cx.updateVersion(version)
        if client_2cx is not None:
            await client_2cx.updateVersion(version)
        header_path = os.path.join(os.path.dirname(__file__), 'headers.json')
        with open(header_path, 'r', encoding='UTF-8') as f:
            defaultHeaders = json.load(f)
            defaultHeaders["APP-VER"] = version
            json.dump(default_headers, f, indent=4, ensure_ascii=False)
        await bot.finish(ev, "更新版本成功", at_sender=True)
    except Exception as e:
        await bot.finish(ev, f'更新版本出错，{e}', at_sender=True)


@sv.scheduled_job('interval', seconds=40)
async def on_arena_schedule():
    # 估计语法糖里有time操作，所以不能用time来读取时间
    global cache, binds, lck, olck, observer, pause

    if pause == 1:
        return

    bot = get_bot()

    # 备份
    cache_new = deepcopy(cache)

    async with lck:
        bind_cache = deepcopy(binds)
    async with olck:
        observer_cache = deepcopy(observer)

    cx_list = []
    id_list = []
    # 获取全部要读取的uid
    for uid in bind_cache:
        info = bind_cache[uid]
        if info['id'] not in id_list:
            id_list.append(info['id'])
            cx_list.append(info["cx"])

    for uid in observer_cache:
        info = observer_cache[uid]
        lenth = len(info['id'])
        for i in range(lenth):
            if info['id'][i] not in id_list:
                id_list.append(info['id'][i])
                cx_list.append(info["cx"][i])

    res_list, uid_list = await query_batch(cx_list, id_list, batch_size=3)

    for uid in bind_cache:
        info = bind_cache[uid]
        try:
            id = int(info['cx'] + info['id'])
            res = res_list[uid_list.index(id)]
            # 分别为jjc排名，pjjc排名，用户名，上一次登录时间，简介
            res = (res['user_info']['arena_rank'],
                   res['user_info']['grand_arena_rank'],
                   res['user_info']["user_name"],
                   res['user_info']['last_login_time'],
                   res["user_info"]["user_comment"])

            if id not in cache:
                cache_new[id] = res
                continue

            last = cache[id]
            cache_new[id] = res

            # 两次间隔排名变化且开启了相关订阅就记录到数据库
            if res[0] != last[0] and info['arena_on']:
                JJCH._add(int(info["id"]), 1, last[0], res[0])
                JJCH._refresh(int(info["id"]), 1)
                # sv.logger.info(f"{info['id']}: JJC {last[0]}->{res[0]}")
            if res[1] != last[1] and info['grand_arena_on']:
                JJCH._add(int(info["id"]), 0, last[1], res[1])
                JJCH._refresh(int(info["id"]), 0)
                # sv.logger.info(f"{info['id']}: PJJC {last[1]}->{res[1]}")

            if res[0] > last[0] and info['arena_on']:
                await bot.send_group_msg(
                    group_id=int(info['gid']),
                    message=f'[CQ:at,qq={info["uid"]}]jjc：{last[0]}->{res[0]}▼{res[0] - last[0]}'
                )

            if res[1] > last[1] and info['grand_arena_on']:
                await bot.send_group_msg(
                    group_id=int(info['gid']),
                    message=f'[CQ:at,qq={info["uid"]}]pjjc：{last[1]}->{res[1]}▼{res[1] - last[1]}'
                )

        except ApiException as e:
            sv.logger.info(f'对台服{info["cx"]}服的{info["id"]}的检查出错\n{format_exc()}')
            if e.code == 6:
                async with lck:
                    delete_arena(uid)
                sv.logger.info(f'已经自动删除错误的uid={info["id"]}')
        except:
            sv.logger.error(f'对台服{info["cx"]}服的{info["id"]}的检查出错\n{format_exc()}')

    for uid in observer_cache:
        info = observer_cache[uid]
        lenth = len(info['id'])
        for i in range(lenth):
            try:
                id = int(info['cx'][i] + info['id'][i])
                res = res_list[uid_list.index(id)]
                res = (res['user_info']['arena_rank'],
                       res['user_info']['grand_arena_rank'],
                       res['user_info']["user_name"],
                       res['user_info']['last_login_time'],
                       res["user_info"]["user_comment"])

                if id not in cache:
                    cache_new[id] = res
                    continue

                last = cache[id]
                cache_new[id] = res
                # if res[4] != last[4]:
                #     await bot.send_group_msg(
                #         group_id=int(info['gid'][i]),
                #         message=f'[CQ:at,qq={info["uid"]}] 您关注的{res[2]}简介更改为{res[4]}'
                #     )

                if int(res[3]) - int(last[3]) > 1800:
                    await bot.send_group_msg(
                        group_id=int(info['gid'][i]),
                        message=f'[CQ:at,qq={info["uid"]}] 您的关注{i+1}已上线'
                    )

                if res[0] != last[0]:
                    await bot.send_group_msg(
                        group_id=int(info['gid'][i]),
                        message=f'[CQ:at,qq={info["uid"]}] 您的关注{i+1} jjc：{last[0]}->{res[0]}'
                    )

                if res[1] != last[1]:
                    await bot.send_group_msg(
                        group_id=int(info['gid'][i]),
                        message=f'[CQ:at,qq={info["uid"]}] 您的关注{i+1} pjjc：{last[1]}->{res[1]}'
                    )
            except ApiException as e:
                sv.logger.info(f'对台服{info["cx"][i]}服的{info["id"][i]}的检查出错\n{format_exc()}')
                if e.code == 6:
                    async with olck:
                        delete_observer(uid, i + 1)
                    sv.logger.info(f'已经自动删除错误的uid={info["id"]}')
            except:
                sv.logger.error(f'对台服{info["cx"][i]}服的{info["id"][i]}的检查出错\n{format_exc()}')
    cache = cache_new


@sv.on_notice('group_decrease.leave')
async def leave_notice(session: NoticeSession):
    global lck, binds, olck
    uid = str(session.ctx['user_id'])
    gid = str(session.ctx['group_id'])
    bot = get_bot()
    if uid in binds:
        async with lck:
            bind_cache = deepcopy(binds)
            info = bind_cache[uid]
            if info['gid'] == gid:
                delete_arena(uid)
                await bot.send_group_msg(
                    group_id=int(info['gid']),
                    message=f'{uid}退群了，已自动删除其bind在本群的竞技场bind推送'
                )
    if uid in observer:
        if observer[uid]['gid'][0] == gid:
            async with olck:
                delete_observer_all(uid)


@sv.on_notice('group_decrease.kick')
async def kick_notice(session: NoticeSession):
    global lck, binds, olck
    uid = str(session.ctx['user_id'])
    gid = str(session.ctx['group_id'])
    bot = get_bot()
    if uid in binds:
        async with lck:
            bind_cache = deepcopy(binds)
            info = bind_cache[uid]
            if info['gid'] == gid:
                delete_arena(uid)
                await bot.send_group_msg(
                    group_id=int(info['gid']),
                    message=f'{uid}被鲨了，已自动删除其bind在本群的竞技场bind推送'
                )
    if uid in observer:
        if observer[uid]['gid'][0] == gid:
            async with olck:
                delete_observer_all(uid)
