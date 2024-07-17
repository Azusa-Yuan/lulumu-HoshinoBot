from json import load, dump
from asyncio import Lock
from os.path import dirname, join, exists
from copy import deepcopy
from traceback import format_exc
from .pcrclient import pcrclient, ApiException, get_headers
from .playerpref import decryptxml
import time
import json
from .jjchistory import *
import asyncio

# 控制并发数 默认为3
semaphore = asyncio.Semaphore(3)  

def _get_cx_name(cx):
    '''
    获取服务器名称
    '''
    if cx == '1':
        cx_name = '美食殿堂'
        return cx_name
    elif cx == '2':
        cx_name = '真步真步王国'
        return cx_name
    elif cx == '3':
        cx_name = '破晓之星'
        return cx_name
    elif cx == '4':
        cx_name = '小小甜心'
        return cx_name
    else:
        cx_name = '未知服务器'
        return cx_name

header_path = os.path.join(os.path.dirname(__file__), 'headers.json')
if not os.path.exists(header_path):
    default_headers = get_headers()
    with open(header_path, 'w', encoding='UTF-8') as f:
        json.dump(default_headers, f, indent=4, ensure_ascii=False)
        

# 头像框设置文件，默认彩色
current_dir = os.path.join(os.path.dirname(__file__), 'frame.json')
if not os.path.exists(current_dir):
    data = {
        "customize": {},
        "default_frame": "color.png"

    }
    with open(current_dir, 'w', encoding='UTF-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


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

# 用于反向存游戏id对应QQ用户
uid_map = {}
type_map = {}
gid_map = {}

# 一些变量初始化
cache = {}

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
    global client_1cx, client_2cx, acinfo_1cx, acinfo_2cx
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

    return client_1cx, client_2cx

client_1cx, client_2cx = get_client()

# 变为登录状态
loop = asyncio.get_event_loop()
if client_1cx is not None:
    loop.run_until_complete(loop.create_task(client_1cx.login()))
if client_2cx is not None:
    loop.run_until_complete(loop.create_task(client_2cx.login()))


# 设置异步锁保证线程安全
lck = Lock()
olck = Lock()
cacheLock = Lock()

def save_binds():
    with open(config, 'w') as fp:
        dump(root, fp, indent=4)
        
def save_observer():
    with open(config_2, 'w') as fp:
        dump(root_2, fp, indent=4)
        
def delete_observer_all(uid):
    observer.pop(uid)
    save_observer()

def delete_arena(uid):
    '''
    订阅删除方法
    '''
    JJCH._remove(binds[uid]['id'])
    binds.pop(uid)
    save_binds()


    
async def checkServer(cx: str):
    global client_1cx, client_2cx
    if cx not in ['1', '2', '3', '4']:
        return None, "服务器选择错误！"
    if cx == '1':
        if client_1cx is None:
            return None, "不支持该服务器！支持的服务器有2/3/4"
        return client_1cx, None
    
    if client_2cx is None:
        return None, "不支持该服务器！支持的服务器只有1"
    return client_2cx, None
    

async def bind(cx: str, id: str, uid: str, gid:str):
    global binds, lck
    _, err = await checkServer(cx)
    if err is not None:
        return None, err

    async with lck:
        last = binds[uid] if uid in binds else None
        binds[uid] = {
            'cx': cx,
            'id': id,
            'uid': uid,
            'gid': gid,
            'arena_on': last is None or last['arena_on'],
            'grand_arena_on': last is None or last['grand_arena_on'],
        }
        save_binds()
        msg = '竞技场bind成功'
    
    return msg, None
    
    
async def add_observer(cx: str, id: str, uid: str, gid:str):
    global olck, observer
    _, err = await checkServer(cx)
    if err is not None:
        return None, err
    
    async with olck:
        if uid in observer:
            if len(observer[uid]['cx']) >= 4:
                msg = '因为服务器性能有限，仅支持关注四名'
                return msg, None
            if id in observer[uid]['id']:
                msg = '您已关注该玩家'
                return msg, None
            observer[uid]['id'].append(id)
            observer[uid]['cx'].append(cx)
            observer[uid]['gid'].append(gid)
        else:
            # 绑定的key是QQ号，关注的key是游戏uid
            observer[uid] = {
                'cx': [cx],
                'id': [id],
                'uid': uid,
                'gid': [gid],
            }
            # print(observer)
        save_observer()
        msg = '竞技场关注成功'
        
    return msg, None
    
    
def pcrjjc_number():
    return len(cache)


# 计算深域进度返回字符串
def calculateDomain(sum):
    # 大关卡
    big = (sum - 1) // 10 + 1
    # 小关卡
    small = sum % 10
    if small == 0 and big > 0:
        small = 10
    return f'{big}-{small}'


async def user_query(cx, id, uid: str):
    global binds, lck, observer
    
    # 判断关注
    if id is None and cx:
        num = int(cx)
        if num == 0:
            return None, '请输入正确的序号'
        if uid not in observer:
            return None, '您还没有关注任何玩家'
        if int(num) > len(observer[uid]['cx']):
            return None, '请输入正确的序号'
        num -= 1
        cx = observer[uid]['cx'][num]
        id = observer[uid]['id'][num]
    
    # 没有服务器和id的情况下
    if id is None and cx is None:
        if uid not in binds:
            return None, "该qq号未bind竞技场"
        else:
            id = binds[uid]['id']
            cx = binds[uid]['cx']
    
    async with lck:
        try:
            res, err = await query(cx, id)
            if err is not None:
                return None, err
            
            cx_name = _get_cx_name(cx)

            last_login_time = int(res['user_info']['last_login_time'])
            last_login_date = time.localtime(last_login_time)
            last_login_str = time.strftime('%Y-%m-%d %H:%M:%S', last_login_date)

            # deep domain 深域
            deepDomain = res["quest_info"]["talent_quest"]

            res = f'''区服：{cx_name}
jjc排名：{res['user_info']["arena_rank"]}
pjjc排名：{res['user_info']["grand_arena_rank"]}
最后登录：{last_login_str}
竞技场场次：{res["user_info"]["arena_group"]}
公主竞技场场次：{res["user_info"]["grand_arena_group"]}
火：{calculateDomain(deepDomain[0]["clear_count"])}    水：{calculateDomain(deepDomain[1]["clear_count"])} 
风：{calculateDomain(deepDomain[2]["clear_count"])}    光：{calculateDomain(deepDomain[3]["clear_count"])} 
暗：{calculateDomain(deepDomain[4]["clear_count"])} '''
            return res, None
                            
        except Exception as e:
            return None, f"查询出错：{e}"


async def send_change(res, callback=None):
    global gid_map, uid_map, type_map, binds, cache, cacheLock
    if res is None:
        return
    id = res['user_info']['viewer_id']
    
    res = (res['user_info']['arena_rank'],
                res['user_info']['grand_arena_rank'],
                res['user_info']["user_name"],
                res['user_info']['last_login_time'],
                res["user_info"]["user_comment"])
    
    if id not in cache:
        cache[id] = res
        return
    
    last = cache[id]
    
    for j, uid in enumerate(uid_map[str(id)]):
        type = type_map[str(id)][j]
        gid = gid_map[str(id)][j]
        try:
            if type < 0:
                # 两次间隔排名变化且开启了相关订阅就记录到数据库
                if res[0] != last[0] and binds[uid]['grand_arena_on']:
                    JJCH._add(int(id), 1, last[0], res[0])
                    JJCH._refresh(int(id), 1)
                if res[1] != last[1] and binds[uid]['grand_arena_on']:
                    JJCH._add(int(id), 0, last[1], res[1])
                    JJCH._refresh(int(id), 0)
                    
                if res[0] > last[0] and binds[uid]['grand_arena_on']:
                    msg = f'jjc:{last[0]}->{res[0]}▼{res[0] - last[0]}'
                    await callback(gid, uid, msg)

                if res[1] > last[1] and binds[uid]['grand_arena_on']:
                    msg = f'pjjc:{last[1]}->{res[1]}▼{res[1] - last[1]}'
                    await callback(gid, uid, msg)
            else:
                if int(res[3]) - int(last[3]) > 1800:
                    msg = f'您的关注{type + 1}已上线'
                    await callback(gid, uid, msg)
                
                if res[0] != last[0]:
                    msg = f'您的关注{type + 1} jjc:{last[0]}->{res[0]}'
                    await callback(gid, uid, msg)

                if res[1] != last[1]:
                    msg = f'您的关注{type + 1} pjjc:{last[1]}->{res[1]}'
                    await callback(gid, uid, msg)
        except Exception as e:
            print(e)
    
    async with cacheLock:
        cache[id] = res
    

async def query(cx: str, id: str, delay: float=0, callback=None):
    client, err = await checkServer(cx)
    if err != None:
        return None, err
    
    async with semaphore:
        try:
            res = await client.callapi('/profile/get_profile', {
                'target_viewer_id': int(cx + id)
            }, delay=delay)
        except Exception:
            # 进行一次重试，发生错误返回空
            try:
                await client.login()
                res = (await client.callapi('/profile/get_profile', {
                    'target_viewer_id': int(cx + id)
                }))
            except Exception as e:
                print("重试继续错误", e)
                return None, f'e'
        
    # 给轮询使用    
    if callback is not None:
        send_change(res, callback)

    return res, None
    
        
def arena_history(uid: str):
    global binds
    if uid not in binds:
        msg = "未bind竞技场"
    else:
        ID = binds[uid]['cx']+binds[uid]['id']
        msg = f'\n{JJCH._select(ID, 1)}'
    return msg


def parena_history(uid: str):
    if uid not in binds:
        msg = '未bind竞技场'
    else:
        ID = binds[uid]['cx']+binds[uid]['id']
        msg = f'\n{JJCH._select(ID, 0)}'
    return msg


async def observer_list(uid: str):
    global observer, cache
    if uid not in observer:
        msg = '您没有关注任何玩家'
        return msg
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
    
    return msg


async def arena_sub(if_grand: bool, if_open: bool,  uid: str):
    key = 'arena_on' if if_grand is None else 'grand_arena_on'
    async with lck:
        if uid not in binds:
            msg = "您还未bind竞技场"
        else:
            binds[uid][key] = if_open
            save_binds()
            msg = "设置成功"
        return msg
    
async def delete_sub(uid: str):
    global binds, lck
    if uid not in binds:
        res = '未bind竞技场'
        return res

    async with lck:
        delete_arena(uid)

    res = '删除竞技场bind成功'
    return res


async def clear_group(gid: str):
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
                  
                    
def delete_observer(uid, num):
    '''
    关注删除方法
    '''
    global observer
    if uid not in observer:
        msg = '您还没有关注任何玩家'
        return msg
    
    
    lenth = len(observer[uid]['id'])
    if 0 < num <= lenth:
        del observer[uid]['id'][num - 1]
        del observer[uid]['cx'][num - 1]
        del observer[uid]['gid'][num - 1]
        save_observer()
        return "删除关注成功"
    return "请输入正确的序号"

async def updateVersion(version):
    if client_1cx is not None:
        await client_1cx.updateVersion(version)
    if client_2cx is not None:
        await client_2cx.updateVersion(version)
    header_path = os.path.join(os.path.dirname(__file__), 'headers.json')
    with open(header_path, 'r+', encoding='UTF-8') as f:
        default_headers["APP-VER"] = version
        json.dump(default_headers, f, indent=4, ensure_ascii=False)
    msg = "更新版本成功"
    return msg

cx_list = []
id_list = []

def updateIdinfo():
    global cx_list, id_list, uid_map, type_map, gid_map
    cx_list = []
    id_list = []
    uid_map = {}
    type_map = {}
    gid_map = {}
    # 获取全部要读取的uid
    for uid in binds:
        info = binds[uid]
        id = info['id']
        cx = info['cx']
        gid = info['gid']
        if id not in id_list:
            id_list.append(id)
            cx_list.append(cx)
            uid_map[cx+id] = [uid]
            type_map[cx+id] = [-1]
            gid_map[cx+id] = [gid]
        else:
            uid_map[cx+id].append(id)
            type_map[cx+id].append(-1)
            gid_map[cx+id].append(gid)

    for uid in observer:
        info = observer[uid]
        lenth = len(info['id'])
        for i in range(lenth):
            id = info['id'][i]
            cx = info["cx"][i]
            gid = info['gid'][i]
            if id not in id_list:
                id_list.append(id)
                cx_list.append(cx)
                uid_map[cx+id] = [uid]
                type_map[cx+id] = [i]
                gid_map[cx+id] = [gid]
            else:
                uid_map[cx+id].append(uid)
                type_map[cx+id].append(i)
                gid_map[cx+id].append(gid)


async def getAllInfo(callback):
    global cx_list, id_list, observer, pause, binds
    
    # 更新id对应qq用户信息
    updateIdinfo()
    
    tasks = []
    for i in range(len(cx_list)):
        tasks.append(asyncio.create_task(query(cx_list[i], id_list[i], 0, callback)))
            
    await asyncio.wait(tasks)

    
async def deleteUser(uid: str, gid: str):
    global lck, binds, olck
    msg = None
    if uid in binds:
        async with lck:
            bind_cache = deepcopy(binds)
            info = bind_cache[uid]
            if info['gid'] == gid:
                delete_arena(uid)
                msg =  f'{uid}退群了,已自动删除其bind在本群的竞技场bind推送'
    if uid in observer:
        if observer[uid]['gid'][0] == gid:
            async with olck:
                delete_observer_all(uid)
    return msg