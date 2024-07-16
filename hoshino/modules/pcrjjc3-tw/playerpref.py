from urllib.parse import unquote
from re import finditer
from base64 import b64decode
from struct import unpack
import os

key = b'e806f6'

def _deckey(s) -> str:
    b = b64decode(unquote(s))
    return bytes([key[i % len(key)] ^ b[i] for i in range(len(b))])

def _decval(k, s):
    b = b64decode(unquote(s))
    key2 = k.encode('utf8') + key
    b = b[0:len(b) - (11 if b[-5] != 0 else 7)]
    return bytes([key2[i % len(key2)] ^ b[i] for i in range(len(b))])

def decryptxml(filename):
    result = {}

    with open(filename, 'r') as fp:
        content = fp.read()
    
    for re in finditer(r'<string name="(.*)">(.*)</string>', content):
        g = re.groups()
        try:
            key = _deckey(g[0]).decode('utf8')
        except:
            continue
        val = _decval(key, g[1])
        if key == 'UDID':
            val = ''.join([chr(val[4 * i + 6] - 10) for i in range(36)])
        elif len(val) == 4:
            '''
            struct.unpack(format, buffer)
            format: 是一个字符串，用于指定如何解析 buffer 中的数据。在你的例子中，'I' 表示解析一个无符号整数（即4个字节的无符号整数）。

            buffer: 是一个字节串（或字节数组），包含要解析的二进制数据。
            '''
            val = str(unpack('I', val)[0])
        result[key] = val
        #except:
        #    pass
    return result

# 自己测试用
if __name__ == "__main__":
    curPath = os.path.dirname(__file__)
    info_dic = decryptxml(curPath+"/2cx_tw.sonet.princessconnect.v2.playerprefs.xml")
    print(info_dic)
    print(decryptxml("./tw.sonet.princessconnect.v2.playerprefs.xml"))
