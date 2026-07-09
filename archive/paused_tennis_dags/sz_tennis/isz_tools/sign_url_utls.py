#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import urllib.parse
import time

# 定义固定的字符映射表
CC = {
    'DCAiy': 'DGi0YA7BemWnQjCl4+bR3f8SKIF9tUz/xhr2oEOgPpac=61ZqwTudLkM5vHyNXsVJ'
}

def Cs(CI):
    """
    字符映射函数，用于s0加密
    
    Args:
        CI (int): 输入索引值
        
    Returns:
        str: 映射后的字符
    """
    CI = CI & 0x3F  # 使用位运算限制索引范围为0-63
    return CC['DCAiy'][CI]

def s0(C8, C9, Cs):
    """
    s0加密函数
    
    Args:
        C8 (str): 输入字符串
        C9 (int): 位数参数
        Cs (function): 字符映射函数
        
    Returns:
        str: 加密后的字符串
    """
    # 如果输入为None，返回空字符串
    if C8 is None:
        return ''

    # 初始化变量
    CI = {}  # 字典对象，存储字符到数字的映射
    CD = {}  # 字典对象，存储临时数据
    Cd = ''  # 当前字符串
    CY = -3 * 0x6a7 + -0x266d + -0xe99 * -0x4  # 计数器
    CV = 0x21e3 + 0x1df2 + -0x30a * 0x15  # 字典计数器
    CR = 0x1 * -0xd37 + -0x233a + 0x3073  # 位数
    CL = []  # 结果数组
    Cb = 0x1162 + -0x447 + 0x15a9  # 位操作缓存
    Cn = 0x4a3 * 0x5 + 0x1d96 + -0x34c5  # 计数器

    # 第一次遍历输入字符串
    for CA in range(len(C8)):
        CC = C8[CA]
        
        if CC not in CI:
            CI[CC] = CV
            CV += 1
            CD[CC] = True

        CN = Cd + CC

        if CN in CI:
            Cd = CN
        else:
            if Cd in CD:
                if ord(Cd[0]) < 256:
                    for _ in range(CR):
                        Cb = (Cb << 1)
                        if Cn == (C9 - 1):
                            Cn = 0
                            CL.append(Cs(Cb))
                            Cb = 0
                        else:
                            Cn += 1

                    Cj = ord(Cd[0])
                    for _ in range(8):
                        Cb = (Cb << 1) | (Cj & 1)
                        if Cn == (C9 - 1):
                            Cn = 0
                            CL.append(Cs(Cb))
                            Cb = 0
                        else:
                            Cn += 1
                        Cj >>= 1
                else:
                    Cj = 1
                    for _ in range(CR):
                        Cb = (Cb << 1) | Cj
                        if Cn == (C9 - 1):
                            Cn = 0
                            CL.append(Cs(Cb))
                            Cb = 0
                        else:
                            Cn += 1
                        Cj = 0

                    Cj = ord(Cd[0])
                    for _ in range(16):
                        Cb = (Cb << 1) | (Cj & 1)
                        if Cn == (C9 - 1):
                            Cn = 0
                            CL.append(Cs(Cb))
                            Cb = 0
                        else:
                            Cn += 1
                        Cj >>= 1

                CY -= 1
                if CY == 0:
                    CY = pow(2, CR)
                    CR += 1
                CD.pop(Cd, None)
            else:
                Cj = CI[Cd]
                for _ in range(CR):
                    Cb = (Cb << 1) | (Cj & 1)
                    if Cn == (C9 - 1):
                        Cn = 0
                        CL.append(Cs(Cb))
                        Cb = 0
                    else:
                        Cn += 1
                    Cj >>= 1

            CY -= 1
            if CY == 0:
                CY = pow(2, CR)
                CR += 1
            CI[CN] = CV
            CV += 1
            Cd = CC

    if Cd:
        if Cd in CD:
            if ord(Cd[0]) < 256:
                for _ in range(CR):
                    Cb <<= 1
                    if Cn == (C9 - 1):
                        Cn = 0
                        CL.append(Cs(Cb))
                        Cb = 0
                    else:
                        Cn += 1

                Cj = ord(Cd[0])
                for _ in range(8):
                    Cb = (Cb << 1) | (Cj & 1)
                    if Cn == (C9 - 1):
                        Cn = 0
                        CL.append(Cs(Cb))
                        Cb = 0
                    else:
                        Cn += 1
                    Cj >>= 1
            else:
                Cj = 1
                for _ in range(CR):
                    Cb = (Cb << 1) | Cj
                    if Cn == (C9 - 1):
                        Cn = 0
                        CL.append(Cs(Cb))
                        Cb = 0
                    else:
                        Cn += 1
                    Cj = 0

                Cj = ord(Cd[0])
                for _ in range(16):
                    Cb = (Cb << 1) | (Cj & 1)
                    if Cn == (C9 - 1):
                        Cn = 0
                        CL.append(Cs(Cb))
                        Cb = 0
                    else:
                        Cn += 1
                    Cj >>= 1

            CY -= 1
            if CY == 0:
                CY = pow(2, CR)
                CR += 1
            CD.pop(Cd, None)
        else:
            Cj = CI[Cd]
            for _ in range(CR):
                Cb = (Cb << 1) | (Cj & 1)
                if Cn == (C9 - 1):
                    Cn = 0
                    CL.append(Cs(Cb))
                    Cb = 0
                else:
                    Cn += 1
                Cj >>= 1

        CY -= 1
        if CY == 0:
            CY = pow(2, CR)
            CR += 1

    Cj = 2
    for _ in range(CR):
        Cb = (Cb << 1) | (Cj & 1)
        if Cn == (C9 - 1):
            Cn = 0
            CL.append(Cs(Cb))
            Cb = 0
        else:
            Cn += 1
        Cj >>= 1

    while True:
        Cb <<= 1
        if Cn == (C9 - 1):
            CL.append(Cs(Cb))
            break
        Cn += 1

    return ''.join(CL)

def compute_hash(input_str: str) -> int:
    """
    实现与JavaScript se函数相同的功能
    
    Args:
        input_str (str): 输入字符串
        
    Returns:
        int: 计算后的32位有符号整数
        
    示例:
        >>> se("https%3A%2F%2Fwxsports.ydmap.cn%2Fsrv100140%2Fapi%2Fpub%2Fbasic%2FgetConfig%3Ft%3D1732507363412")
        -1217143439
        >>> se("https%3A%2F%2Fwxsports.ydmap.cn%2Fsrv200%2Fapi%2Fpub%2Fbasic%2FgetConfig%3Ft%3D1732507709655")
        784062962
    """
    result = 0
    
    for char in input_str:
        # 1. result << 7
        # 2. (result << 7) - result
        # 3. ((result << 7) - result) + 398
        # 4. 最后加上字符码值
        # 5. 使用 & 0xFFFFFFFF 保持在32位范围内
        # 6. 将无符号整数转换为有符号整数
        result = ((result << 7) - result + 398 + ord(char)) & 0xFFFFFFFF
        if result & 0x80000000:
            result = -((result ^ 0xFFFFFFFF) + 1)
    
    return result


def encode_uri_component(uri: str) -> str:
    """
    对 URI 进行编码。
    
    该函数使用 urllib.parse.quote 对输入 URI 进行编码，
    并指定安全字符集为 ~()*!.\'。
    
    Args:
        uri (str): 需要编码的 URI 字符串
        
    Returns:
        str: 编码后的 URI 字符串
    """
    return urllib.parse.quote(uri, safe='~()*!.\'')


def test_s0():
    """
    测试s0加密函数
    """
    # 测试用例1
    test1_input = "-1938548878|0|1732437458668|1"
    test1_expected = "n4+xgDuDBDcDnAWGkWD/D0WobeiK5+mqw4G=pFe4D"
    test1_result = s0(test1_input, 6, Cs)
    print('\n测试用例1:')
    print('输入:', test1_input)
    print('预期输出:', test1_expected)
    print('实际输出:', test1_result)
    print('测试结果:', '通过' if test1_result == test1_expected else '失败')

    # 测试用例2
    test2_input = "-565752108|0|1732437342710|1"
    test2_expected = "n4fx9i0=eYqeqDKDtD/GWH4QqqiwzLwoo4TD"
    test2_result = s0(test2_input, 6, Cs)
    print('\n测试用例2:')
    print('输入:', test2_input)
    print('预期输出:', test2_expected)
    print('实际输出:', test2_result)
    print('测试结果:', '通过' if test2_result == test2_expected else '失败')

    # 测试用例3
    test3_input = "-278611504|0|1732454625451|1"
    test3_expected = "n4mxyDBD9D20i=D7DnDBdFOK0QmgkbhDlhoTD"
    test3_result = s0(test3_input, 6, Cs)
    print('\n测试用例3:')
    print('输入:', test3_input)
    print('预期输出:', test3_expected)
    print('实际输出:', test3_result)
    print('测试结果:', '通过' if test3_result == test3_expected else '失败')


def test_url_generation(current_time):
    """
    测试URL生成功能
    测试用例：https://wxsports.ydmap.cn/srv200/api/pub/basic/getConfig?t=1732463129946&timestamp__1762=YqRx2D0DcA0%3D0QqDsYExtDnDjgO3ekaK4D
    """
    # 测试参数
    base_url = f"https://wxsports.ydmap.cn/srv100140/api/pub/sport/venue/getSportVenueConfig?salesItemId=100000&curDate=1748361600000&venueGroupId=&t=1748368630980"
    print(f"✅[RESULT] base_url: {base_url}")
    
    # 1 先encodeURIComponent
    encoded_url = encode_uri_component(base_url)
    print(f"✅[RESULT] encoded_url: {encoded_url}")

    # 2 计算encoded_url的hash值
    url_hash = compute_hash(encoded_url)
    print(f"✅[RESULT] url_hash: {url_hash}")

    # 4 使用s0函数生成timestamp__1762参数
    # import time
    # current_time = int(time.time() * 1000)
    # print(current_time)
    # current_time = 1748368676667
    timestamp_1762 = s0(f"{url_hash}|0|{current_time}|1", 6, Cs)
    print(f"✅[RESULT] timestamp_1762: {timestamp_1762}")

    # 5 构建最终的完整URL
    full_url = f"{base_url}&timestamp__1762={timestamp_1762}"        

    # 判断是否与预期输出一致
    print(f"[RESULT] full_url: {full_url}")


def ydmap_sign_url(base_url: str, current_time: int, key_name: str) -> str:
    """
    ydmap 签名url
    """
    print(f"✅[RESULT] base_url: {base_url}")
    
    # 1 先encodeURIComponent
    encoded_url = encode_uri_component(base_url)
    print(f"✅[RESULT] encoded_url: {encoded_url}")

    # 2 计算encoded_url的hash值
    url_hash = compute_hash(encoded_url)
    print(f"✅[RESULT] url_hash: {url_hash}")

    url_sign_key = s0(f"{url_hash}|0|{current_time}|1", 6, Cs)
    print(f"✅[RESULT] {key_name}: {url_sign_key}")

    # 5 构建最终的完整URL
    full_url = f"{base_url}&{key_name}={url_sign_key}"        

    # 判断是否与预期输出一致
    print(f"[RESULT] full_url: {full_url}")
    
    # 返回完整URL
    return full_url
