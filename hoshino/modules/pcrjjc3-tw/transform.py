from json import load, dump
from os.path import dirname, join, exists


# 负责将老用户数据转化为新的  包括绑定和关注
# 读取bind和关注配置
curpath = dirname(__file__)
config = join(curpath, 'binds.json')
config_2 = join(curpath, 'observer.json')