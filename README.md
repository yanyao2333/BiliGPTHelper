<h2 align="center">✨Bilibili GPT Bot✨</h2>
<h5 align="center">把ChatGPT放到B站里！更高效、快速的了解视频内容</h5>

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-311/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![wakatime](https://wakatime.com/badge/user/41ab10cc-ec82-41e9-8417-9dcf5a9b5947/project/cef4699c-8d07-4cf0-9d0a-ef83fb353b82.svg)](https://wakatime.com/badge/user/41ab10cc-ec82-41e9-8417-9dcf5a9b5947/project/cef4699c-8d07-4cf0-9d0a-ef83fb353b82)

### 🌟 介绍

b站那种AI课代表都见过吧？看起来超级酷！所以我也搞了个捏

### 📜 声明

当你查阅、下载了本项目源代码或二进制程序，即代表你接受了以下条款：

1. 本项目和项目成果仅供技术，学术交流和Python3性能测试使用\
2. 本项目贡献者编写该项目旨在学习Python3 ，提高编程水平\
3. 用户在使用本项目和项目成果前，请用户了解并**遵守当地法律法规**，如果本项目及项目成果使用过程中存在违反当地法律法规的行为，请勿使用该项目及项目成果\
4. **法律后果及使用后果由使用者承担**\
5. 开发者（yanyao2333）**不会**
   将任何用户的cookie、个人信息收集上传至除b站官方的其他平台或服务器。同时，开发者（yanyao2333）不对任何造成的后果负责（包括但不限于账号封禁等后果），如有顾虑，请谨慎使用

若用户不同意上述条款**任意一条**，**请勿**使用本项目和项目成果

### 😎 特性

- [x] 使用大模型生成总结
- [x] 已支持Claude、Openai大语言模型
- [x] 已支持openai的whisper和本地whisper语音转文字
- [x] 支持热插拔的asr和llm模块，基于优先级和运行稳定情况调度
- [x] 优化prompt，达到更好的效果、更高的信息密度，尽量不再说废话。还可以让LLM输出自己的思考、评分，让摘要更有意思
- [x] 支持llm返回消息格式不对自动修复
- [x] 支持艾特和私信两种触发方式
- [x] 支持视频缓存，避免重复生成
- [x] 可自动检测和刷新b站cookie（实验性功能）
- [x] 支持自定义触发关键词
- [x] 支持保存当前处理进度，下次启动时恢复
- [x] 支持一键生成并不精美的运行报告，包含一些图表

### 🚀 使用方法

#### 一、通过docker运行

现在有两个版本的docker，代码都是最新版本，只是包不一样:
1. latest 这个版本不包含whisper，也就是只能用来总结包含字幕的视频。这个镜像只有200多m，适合偶尔使用
2. with_whisper 这个版本包含whisper，大小达到了2g，但是可以使用**本地**语音转文字生成字幕



```shell
docker pull yanyaobbb/bilibili_gpt_helper:latest
或
yanyaobbb/bilibili_gpt_helper:with_whisper
```

```shell
docker run -d \
    --name biligpthelper \
    -v 你本地的biligpt配置文件目录:/data \
    yanyaobbb/bilibili_gpt_helper:latest（with_whisper）
```

首次运行会创建模板文件，编辑config.yml，然后重启容器即可

#### 二、源代码运行

1. 克隆并安装依赖

```shell
git clone https://github.com/yanyao2333/BiliGPTHelper.git
cd BiliGPTHelper
pip install -r requirements.txt
```

2. 编辑config.yml

3. 运行，等待初始化完成

```shell
python main.py
```

#### 触发方式

##### 私信

1. 手机端视频页分享视频并附带一条文字消息，例如"总结一下"，即可触发总结
2. 发送"[关键字] 视频bv号"（例如"总结一下 BVxxxxxxx"）

##### at

在评论区发送关键字即可\
**但是你b评论区风控真的太严格了，体验完全没私信好，还污染评论区（所以，你懂我意思了吧）**


### 💸 这玩意烧钱吗

#### Claude

claude才是唯一真神！！！比gpt-3.5-turbo-16k低将近一半的价格（指prompt价格），还有100k的上下文窗口！输出的格式也很稳定，内容质量与3.5不相上下。

现在对接了个aiproxy的claude接口，简直香炸...gpt3.5是什么？真不熟

#### GPT

根据我的测试，单纯使用**gpt-3.5-turbo-16k**，20元大概能撑起5000次时长为10min左右的视频总结（在不包括格式不对重试的情况下）

但在我的测试中，gpt3.5返回的内容已经十分稳定，我并没有遇到过格式不对的情况，所以这个价格应该是可以接受的

如果你出现了格式不对的情况，可以附带bad case示例**发issue**，我尝试优化下prompt

#### OPENAI WHISPER

相比之下这个有点贵，20元能转大概8小时视频

### 🤔 目前问题

1. 无法回复楼中楼评论的at（我实在搞不懂评论的继承逻辑是什么，设置值了对应id也没法发送楼中楼，我好笨）
2. 不支持多p视频的总结（这玩意我觉得没法修复，本来都是快要被你b抛弃的东西）
3. 你b严格的审查机制导致私信/回复消息触碰敏感词会被屏蔽

### 📝 TODO

- [ ] 支持多账号负载均衡 **(on progress)**
- [ ] 能够画思维导图（拜托，这真的超酷的好嘛）

### ❤ 感谢

[Nemo2011/bilibili-api](https://github.com/Nemo2011/bilibili-api/) | 封装b站api库
[JetBrains](https://www.jetbrains.com) | 感谢JetBrains提供的免费license

### [开发文档](./DEV_README.md)

### 📚 大致流程（更详细内容指路 [开发文档](./DEV_README.md)）

```mermaid
sequenceDiagram
    participant 用户
    participant 监听器
    participant 处理链
    participant 发送器
    participant LLMs
    participant ASRs
    用户 ->> 监听器: 发送私信或at消息消息
    alt 消息触发关键词
        监听器 ->> 处理链: 触发关键词，开始处理
    else 消息不触发关键词
        监听器 ->> 用户: 不触发关键词，不处理
    end
    处理链 ->> 处理链: 检查是否有缓存
    alt 有缓存
        处理链 ->> 发送器: 有缓存，直接发送
    end
    处理链 ->> 处理链: 检查是否有字幕
    alt 有字幕
        处理链 ->> LLMs: 根据视频简介、标签、热评、字幕构建prompt并生成摘要
    else 没有字幕
        处理链 ->> ASRs: 转译视频
        ASRs ->> ASRs: 自动调度asr插件，选择一个发送请求
        ASRs ->> 处理链: 转译完成
        处理链 ->> LLMs: 根据视频简介、标签、热评、字幕构建prompt并生成摘要
    end
    LLMs ->> 处理链: 摘要内容
    处理链 ->> 处理链: 解析摘要是否符合要求
    alt 摘要符合要求
        处理链 ->> 发送器: 发送摘要
        发送器 ->> 用户: 发送成功
    else 摘要不符合要求
        处理链 ->> 处理链: 使用指定prompt修复摘要
        处理链 ->> 发送器: 发送摘要
        发送器 ->> 用户: 发送成功
    end
```