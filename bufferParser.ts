import { ExtraBufData, RoomData, RoomDataMember } from '../interfaces/wechat/types/database';
import logger from './logger';
import * as protobuf from 'protobufjs';

/**
 * 字节数据解析工具类
 */
export class BufferParser {
  private static readonly logger = logger.createContextLogger('BufferParser');

  /**
   * ExtraBuf字段映射表
   */
  private static readonly extraBufMap: Record<string, string> = {
    '74752C06': '性别[1男2女]',
    '46CF10C4': '个性签名',
    'A4D9024A': '国',
    'E2EAA8D1': '省',
    '1D025BBF': '市',
    'F917BCC0': '公司名称',
    '759378AD': '手机号',
    '4EB96D85': '企微属性',
    '81AE19B4': '朋友圈背景',
    '0E719F13': '备注图片',
    '945f3190': '备注图片2'
  };

  /**
   * 结果字段映射表
   */
  private static readonly resultMap: Record<string, string> = {
    '性别[1男2女]': 'gender',
    '个性签名': 'signature',
    '国': 'country',
    '省': 'province',
    '市': 'city',
    '公司名称': 'companyName',
    '手机号': 'phone',
    '企微属性': 'weworkProperty',
    '朋友圈背景': 'wallpaper',
    '备注图片': 'avatarUrl',
    '备注图片2': 'bigAvatarUrl'
  };

  /**
   * 解析联系人ExtraBuf字段
   * @param extraBuf 二进制数据
   * @returns 解析后的数据对象
   */
  static parseExtraBuf(extraBuf: Buffer): ExtraBufData | null {
    if (!extraBuf.length) {
      return null;
    }
    
    try {
      const result: ExtraBufData = {};

      for (const [hexKey, fieldName] of Object.entries(this.extraBufMap)) {
        const bufKey = Buffer.from(hexKey, 'hex');
        const offset = extraBuf.indexOf(bufKey);
        if (offset === -1) {
          result[this.resultMap[fieldName]] = '';
          continue;
        }

        const typeOffset = offset + bufKey.length;
        const typeId = extraBuf[typeOffset];
        const dataOffset = typeOffset + 1;

        switch (typeId) {
          case 0x04: // 32位整数
            result[this.resultMap[fieldName]] = extraBuf.readInt32LE(dataOffset);
            break;

          case 0x18: // UTF-16字符串
            {
              const length = extraBuf.readInt32LE(dataOffset);
              const strBuf = extraBuf.slice(dataOffset + 4, dataOffset + 4 + length);
              result[this.resultMap[fieldName]] = strBuf.toString('utf16le').replace(/\0+$/, '');
            }
            break;

          case 0x17: // UTF-8字符串
            {
              const length = extraBuf.readInt32LE(dataOffset);
              const strBuf = extraBuf.slice(dataOffset + 4, dataOffset + 4 + length);
              result[this.resultMap[fieldName]] = strBuf.toString('utf8').replace(/\0+$/, '');
            }
            break;

          case 0x05: // 64位整数
            result[this.resultMap[fieldName]] = `0x${extraBuf.slice(dataOffset, dataOffset + 8).toString('hex')}`;
            break;
        }
      }

      return result;
    } catch (error) {
      this.logger.error('Failed to parse ExtraBuf:', { error });
      return null;
    }
  }

  /**
   * 解析RoomData字段
   * @param roomData Buffer类型的数据
   * @returns 解析后的数据对象
   */
  static parseRoomData(roomData: Buffer): RoomData | null {
    if (!roomData) {
      return null;
    }

    try {
      // 直接转换为UTF-8字符串
      const decodedStr = roomData.toString('utf8');

      // 按行分割，过滤空行
      const wxids = decodedStr.split('\n')
        .map(line => line.trim())
        .filter(line => line && line.startsWith('wxid_'));

      this.logger.debug('Decoded RoomData:', { wxids });

      // 转换为RoomData格式
      const result: RoomData = {
        members: wxids.map(wxid => ({
          '1': wxid,
          '2': '1' // 默认成员标志为1
        }))
      };

      return result;
    } catch (error) {
      this.logger.error('Failed to parse RoomData:', { 
        error, 
        roomData: roomData.toString('hex'),
        roomDataLength: roomData.length 
      });
      return null;
    }
  }
}
