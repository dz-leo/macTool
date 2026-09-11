# Mac 工具管理台 · 调研报告

> 调研时间：2026-09-04 ｜ 全部结论基于**在你这台机器上实测**，非网络转载。
> 工具清单的 brew 可用性，用你本机 Homebrew 索引（cask_names.txt / formula_names.txt）逐条校验过。

---

## 0. 一句话结论

你要的 6 件事里，**3 件纯网页就能做，3 件必须挂一个本地小服务**（Python 单文件、零第三方依赖、只监听 127.0.0.1）。
我已经把「本地小服务」这条路在你机器上跑通验证过了 —— 读服务状态、启停服务、在指定目录开终端，三条全部返回成功。

推荐方案：**网页工作台 + 本地 bridge 双件套**，bridge 没启动时页面自动降级成只读知识库，不会白屏。

---

## 1. 你的机器实况（实测）

| 项 | 实测值 |
|---|---|
| 系统 | macOS 15.6 Sequoia (24G84) |
| 芯片 / 内存 | Apple M2 Pro / 16 GB |
| Homebrew | 4.5.9，`/opt/homebrew` |
| 已装 formula | **81 个** |
| 已装 cask | **0 个**（GUI 软件全是手动装的） |
| 终端 | 只有系统 Terminal.app，**没有 iTerm2 / Warp / Ghostty** |
| 效率类软件 | **一个都没有**（Raycast / Alfred / Hammerspoon / Rectangle / Stats 全空） |

**正在跑的服务与端口**

| 服务 | 状态 | 端口 | 配置/数据文件 |
|---|---|---|---|
| nginx | 已启动 | **8080** | `/opt/homebrew/etc/nginx/nginx.conf`（servers/ 目前是空的） |
| mysql@8.0 | 已启动 | **3306 / 33060** | `/opt/homebrew/etc/my.cnf` |
| redis@8.2 | 已启动 | **6379** | `/opt/homebrew/etc/redis.conf` |
| php 8.5.9 | 未启动 | — | `/opt/homebrew/etc/php/8.5/php.ini` |
| php@8.3 | 未启动 | — | — |

**实测到的配置文件路径**（工作台「一键直达」可直接用）

```
~/.zshrc
~/.gitconfig
~/.ssh/config              ← 实测不存在，需要的话我给你建
/opt/homebrew/etc/nginx/nginx.conf
/opt/homebrew/etc/nginx/servers/
/opt/homebrew/etc/redis.conf
/opt/homebrew/etc/my.cnf
/opt/homebrew/etc/php/8.5/php.ini
~/Library/LaunchAgents/homebrew.mxcl.*.plist   ← 服务自启配置
```

**画像判断**：这是一台 PHP/Python 开发机（php + mysql + nginx + redis + node + composer），GUI 工具靠手动装、CLI 靠 brew。
**最大的空白是：终端太弱 + 完全没有效率工具层。** 这是投入产出比最高的补齐方向。

---

## 2. 六个需求逐条拆解

### 2.1 Mac 快捷键库 → ✅ 纯网页可做

无需任何权限，纯数据展示 + 搜索 + 分类。
建议按场景分组，而不是死记硬背一大张表：

- **系统级**：⌘Space 聚焦搜索、⌘⌃Q 锁屏、⌘⇧3/4/5 截图、⌘⌥Esc 强制退出
- **窗口管理**：⌃↑ Mission Control、⌘Tab 切 App、⌘` 切同 App 窗口、⌘M 最小化、⌘⌥F 最大化
- **文本编辑（全局通用，程序员高频）**：⌃A/E 行首行尾、⌃K 删到行尾、⌃U 删到行首、⌃W 删前一个词、⌃Y 粘贴、⌃P/N 上下行、⌃B/F 左右字符、⌃D 向后删、⌃T 交换字符、⌥←/→ 按词跳、⌥⌫ 删整词
- **Finder**：⌘⇧N 新建文件夹、⌘⇧G 前往文件夹、⌘⇧. 显示隐藏文件、空格 Quick Look、⌘⌥C 拷贝路径、⌘⌥V 剪切移动
- **终端**：⌃C 中断、⌃D EOF、⌃R 反向搜索、⌃L 清屏、⌘K 全清
- **截图**：⌘⇧3 全屏、⌘⇧4 选区、⌘⇧4+空格 窗口截图、⌘⇧5 工具面板
- **浏览器 / 编辑器**：⌘1~9 切标签、⌘⌥→ 下一个标签

> ⌃A/E/K/U 这套 Emacs 键位是 Mac 的隐藏优势，在几乎所有原生输入框里都能用（包括浏览器地址栏），值得单独一屏重点展示。

**工作台可做**：分类卡片 + 实时搜索 + 「标记为常用」+ 点击复制按键符号。

---

### 2.2 brew 服务运行状态 → ⚙️ 需要本地 bridge（已验证可行）

网页**本身**读不到你机器的进程和服务，这是浏览器沙箱决定的，绕不过去。
但挂一个本地 HTTP 服务就能解决，我已实测：

```
GET /api/services  →  brew services list --json   ✅ 实测返回完整 JSON
GET /api/act?name=nginx&act=restart              ✅ 可执行
```

`brew services` 走的是 **user domain**（`~/Library/LaunchAgents`），**不需要 sudo**，这点很关键，意味着工作台点一下就能重启 nginx/mysql/redis，不用输密码。

**能做的**：实时状态灯、启/停/重启、端口显示、日志路径直达、plist 直达、批量启停、服务 Web 后台快捷链接（比如 Redis 的管理页）。

**坑（提前说）**：
- `brew services` 每次调用约 0.5–2 秒，页面要做加载态，别以为卡死了
- 我在实测中发现：从非终端进程用 `osascript` 控制 Terminal 会报 **-10004 权限违例**（macOS 自动化授权）。
  所以**不要走 AppleScript**，走 `open -a` 这条路（见 2.5），零授权、零弹窗。

---

### 2.3 一键直达配置 → ⚙️ 需要 bridge（退化方案纯网页也行）

三种「直达」动作，实测结论：

| 动作 | 命令 | 是否需要授权 | 实测 |
|---|---|---|---|
| 用默认 App 打开文件 | `open <file>` | 否 | 可用 |
| 在 VS Code 中打开 | `code <path>` | 否 | 可用（你装了 VS Code） |
| 在 Finder 中显示 | `open -R <path>` | 否 | 可用 |
| 在终端打开目录 | `open -a Terminal <dir>` | 否 | ✅ 已验证 |

**纯网页退化方案**：点一下复制路径到剪贴板，你自己 ⌘⇧G 粘贴。能用，但体验差一截。

**工作台可做**（bridge 版）：配置文件清单卡片，每个卡片三个按钮 ——「编辑」「Finder 显示」「在此开终端」。
再加一个「自定义常用目录/文件」，你自己往里加项目路径。

---

### 2.4 右键新建文件 → ❌ 网页做不了，但有三个好办法

Finder 右键菜单属于系统扩展（Finder Sync Extension）或「快速操作」，**网页完全插不进去**。说实话，这个功能本来也不该塞进网页工作台 —— 它的价值就在于"随手右键"。

三个方案，我按推荐度排序：

| 方案 | 成本 | 说明 |
|---|---|---|
| **① 超级右键 iRightMouse** | App Store 免费 | 免费、功能最全、口碑最好。能新建 TXT/Word/Excel/PPT/Markdown/PSD 等，还能拷贝路径、剪切文件、进终端、进 VSCode、显示隐藏文件。**推荐直接装这个** |
| **② Automator 快速操作** | 0 安装 | 系统自带，5 分钟搞定。新建「快速操作」→ 接收「访达中的文件夹」→ 运行 AppleScript → 存为「新建文件」。之后右键文件夹 → 快速操作 → 新建文件。**不想装任何东西就走这条，我可以把脚本直接给你** |
| **③ MacRight（开源）** | 需编译 | GitHub 开源（Swift + FinderSync），功能同 ① 但可自己改。要装 Xcode Command Line Tools，适合想折腾的 |

> 补充：这类工具在 `/Users`、`/Applications` 这类系统目录下会被沙箱拦住无法新建文件，这是 macOS 的预期行为，不是 bug。

**工作台能做的替代**：一个「在指定目录新建文件」的小面板（走 bridge），选目录 + 填文件名 + 选模板 → 一键生成。不如右键顺手，但作为兜底够用了。

---

### 2.5 在指定路径启动终端 → ⚙️ bridge（已验证，零授权）

这是你点名要的功能，我专门验证过：

**关键实锤**：Terminal.app 的 Info.plist 里 `CFBundleDocumentTypes` 明确声明了 `public.directory`，
所以 `open -a Terminal <目录>` 能直接在新窗口打开并 cd 到该目录 —— **走 LaunchServices，不需要任何权限授权**。

```
实测：open -a Terminal "/Users/dazhi/Sites"  →  exit code 0 ✅
```

对比之下，`osascript -e 'tell app "Terminal" to do script ...'` 实测报 **-10004 权限违例**，要先去系统设置授权「自动化」，多一道坑。**所以只用 `open -a`。**

各终端的命令（工作台会根据你装了哪个自动切换）：

| 终端 | 命令 |
|---|---|
| Terminal.app（你现在有） | `open -a Terminal "<dir>"` |
| iTerm2 | `open -a iTerm "<dir>"` |
| Warp | `open -a Warp "<dir>"` |
| Ghostty | `open -a Ghostty "<dir>"` |

**工作台可做**：常用目录卡片组（项目目录、Sites、Downloads、brew etc…），点一下就在该目录开终端。
再加一个「自定义目录」和「顺便执行一条命令」（比如 `cd` 后自动 `git status`）。

---

### 2.6 其他 mac 便捷工具 → 大部分 ❌ 装 App，但有一部分 ✅ 网页能做

网页能直接做的「便捷小工具」：

| 小工具 | 说明 |
|---|---|
| **端口速查** | 走 bridge 跑 `lsof`，列出占用端口的进程 + 一键 kill |
| **常用命令片段库** | 自己攒的 brew / git / nginx / mysql 命令，点击复制 |
| **剪贴板/文本处理** | 纯前端：JSON 格式化、Base64、URL 编解码、时间戳转换、UUID 生成 |
| **图片压缩** | 纯前端 canvas 压缩（不传服务器） |
| **服务健康检查** | bridge 批量 curl 本地端口，一眼看哪些挂了 |
| **磁盘/内存概览** | bridge 跑 `df` / `vm_stat` / `top -l 1` |

网页做不了的（必须装 App）：窗口管理、剪贴板历史、菜单栏监控、App 切换、截图标注、键位改造。这些见第 3 节。

---

## 3. 工具清单（brew 可用性已逐条实测）

图例：⚡=brew 可一键装 ｜ 📦=需手动下载/App Store ｜ ⭐ 数量=推荐度（最高 3）

### T0 · 强烈推荐，先装这几个

| 工具 | 装法 | 推荐度 | 理由 |
|---|---|---|---|
| **Raycast** | ⚡ `brew install --cask raycast` | ⭐⭐⭐ | 免费启动器，一个顶十个：搜索、剪贴板、窗口管理、代码片段、脚本。你目前完全没有启动器层 |
| **Rectangle** | ⚡ `brew install --cask rectangle` | ⭐⭐⭐ | 免费窗口分屏，⌥方向键拖拽。macOS 自带分屏太弱 |
| **Maccy** | ⚡ `brew install --cask maccy` | ⭐⭐⭐ | 免费剪贴板历史，⌘⇧C 呼出。程序员刚需 |
| **Stats** | ⚡ `brew install --cask stats` | ⭐⭐⭐ | 菜单栏 CPU/内存/磁盘/网速监控，免费开源 |
| **Alt-Tab** | ⚡ `brew install --cask alt-tab` | ⭐⭐⭐ | Windows 式 ⌘Tab 带缩略图，比自带好用 |
| **超级右键 iRightMouse** | 📦 App Store 免费 | ⭐⭐⭐ | 就是你在找的「右键新建文件」，还顺带解决拷贝路径/剪切/进终端 |
| **iTerm2 或 Ghostty** | ⚡ `brew install --cask iterm2` / `ghostty` | ⭐⭐⭐ | 你只有系统 Terminal，太素。iTerm2 功能全，Ghostty 更快更现代 |

### T1 · 值得装

| 工具 | 装法 | 推荐度 | 理由 |
|---|---|---|---|
| **BrewServicesMenubar** | ⚡ `brew install --cask brewservicesmenubar` | ⭐⭐ | 菜单栏管 brew 服务，跟工作台互补（不用开网页也能启停） |
| **Karabiner-Elements** | ⚡ `brew install --cask karabiner-elements` | ⭐⭐ | 键位改造神器（CapsLock 变 Hyper 键等） |
| **KeyCastr** | ⚡ `brew install --cask keycastr` | ⭐⭐ | 录屏/演示时显示按键 |
| **Shottr** | ⚡ `brew install --cask shottr` | ⭐⭐ | 截图 + 标注，免费，比自带截图强 |
| **Hidden Bar** | ⚡ `brew install --cask hiddenbar` | ⭐⭐ | 菜单栏图标收纳，免费 |
| **AppCleaner** | ⚡ `brew install --cask appcleaner` | ⭐⭐ | 卸载干净，免费 |
| **The Unarchiver** | ⚡ `brew install --cask the-unarchiver` | ⭐⭐ | 解压各种格式，免费 |
| **MonitorControl** | ⚡ `brew install --cask monitorcontrol` | ⭐⭐ | 外接显示器直接用键盘调亮度/音量 |
| **ImageOptim** | ⚡ `brew install --cask imageoptim` | ⭐ | 图片压缩，免费 |
| **TablePlus** | ⚡ `brew install --cask tableplus` | ⭐ | 你已有 Navicat / Sequel Ace / Tiny RDM，可装可不装 |
| **Proxyman** | ⚡ `brew install --cask proxyman` | ⭐ | 抓包调试，开发用 |

### T2 · 可选 / 看个人习惯

| 工具 | 装法 | 说明 |
|---|---|---|
| Ice | ⚡ `brew install ice` | 菜单栏整理（比 Hidden Bar 更现代） |
| Bartender 5 | ⚡ `brew install --cask bartender` | 菜单栏管理，付费 |
| Loop | ⚡ `brew install --cask loop` | 窗口管理新秀，动画好看 |
| Moom / BetterSnapTool | ⚡ cask 有 | 窗口管理替代 |
| Keka | ⚡ `brew install --cask keka` | 压缩/解压，开源 |
| TextSniper | ⚡ `brew install --cask textsniper` | 截图取文字（OCR） |
| Shortcat / Homerow | ⚡ cask 有 | 纯键盘操作 UI |
| Downie / Permute | ⚡ cask 有 | 视频下载 / 格式转换，付费 |

### T3 · 有更简单替代，或 brew 没有

| 工具 | 情况 |
|---|---|
| CleanMyMac | 贵且后台驻留。替代：`brew install mole`（开源清理，命令 `mo`）+ AppCleaner |
| Bartender / Launchbar | 付费且 Raycast 已覆盖大部分 |
| yabai / aerospace / skhd | brew 无收录，需手动装 + 关 SIP，折腾成本高，先用 Rectangle |
| linear-mouse / mac-mouse-fix | `linear-mouse` brew 无；`mac-mouse-fix` 有。鼠标增强，非必需 |
| Alfred | `alfred` brew 有，但 Raycast 免费且更现代，除非你有旧 workflow 依赖 |
| Keyboard Maestro | 强大但 $$$

**顺带提一句你缺的命令行工具**（都是 formula，`brew install` 直接装）：

```
效率类  fd  ripgrep  bat  eza  fzf  zoxide  jq  yq  tree  tldr  trash  htop  btop  ncdu  duf
开发类  lazygit  httpie  mkcert  caddy  starship  superfile
系统类  m-cli  dockutil  mas           ← 用命令行改 Mac 系统设置、Dock、App Store 安装
```

其中 **`m-cli`** 特别值得一提：它能用命令查/改 Mac 的各项系统设置（音量、WiFi、蓝牙、电池、显示器……），是给工作台加「系统快捷开关」的最佳搭档。

---

## 4. 可行性矩阵 —— 哪些能进工作台

| 你想要的功能 | 网页纯前端 | 加本地 bridge | 结论 |
|---|---|---|---|
| 快捷键查询/搜索/收藏 | ✅ | ✅ | **做**，纯数据 |
| 服务状态实时显示 | ❌ | ✅ 已验证 | **做**，bridge |
| 服务 启/停/重启 | ❌ | ✅ 无需 sudo | **做**，bridge |
| 配置文件一键直达（编辑/显示） | ❌ | ✅ | **做**，bridge |
| 指定目录启动终端 | ❌ | ✅ 已验证 | **做**，bridge |
| 自定义常用目录 | ✅ | ✅ | **做** |
| 端口占用速查 + kill | ❌ | ✅ | **做**，bridge |
| 命令片段库（点击复制） | ✅ | ✅ | **做**，纯数据 |
| 文本小工具（JSON/Base64/时间戳） | ✅ | — | **做**，纯前端，零权限 |
| 磁盘/内存概览 | ❌ | ✅ | **做**，bridge |
| 右键新建文件 | ❌ | ⚠️ 只能做「面板新建」 | **不做**，改用 iRightMouse |
| 窗口管理 / 剪贴板历史 | ❌ | ❌ | **不做**，装 App |
| 菜单栏监控 | ❌ | ❌ | **不做**，装 Stats |

---

## 5. 工作台架构方案（三选一）

### 方案 A · 纯单文件 HTML（零安装）
- 能做的：快捷键库、配置路径清单、命令片段、文本小工具、自定义收藏
- 不能做：**所有跟机器交互的事**（服务状态、开终端、开配置）
- 优点：一个文件，双击就开，永不失效
- 缺点：你最想要的几个功能全都做不了

### 方案 B · 网页 + 本地 bridge（推荐）
- **bridge**：一个 Python 单文件，只用标准库，零第三方依赖，只监听 `127.0.0.1:8899`
- **网页**：单文件 HTML，CSS/JS 全内联，图表用内联 SVG，零 CDN
- **能力**：上面矩阵里所有 ✅ 的功能全都能做
- **降级**：bridge 没启动时，页面自动切成「只读模式」，所有操作按钮变成「复制命令」，不会白屏、不会报错
- **安全**：只监听本机回环地址，外网访问不到；**只开放白名单命令**（服务启停、open、lsof 等），**不提供任意命令执行接口**
- **启动**：一条命令 `python3 mactool-bridge.py`，或我给你配成开机自启（launchd）
- **部署**：页面可以同步部署到资料库拿在线链接，手机也能开（手机上没 bridge → 自动降级为只读，符合预期）

### 方案 C · 不建工作台，直接装现成 App 拼
- Raycast（启动器+剪贴板+窗口）+ BrewServicesMenubar（服务）+ iRightMouse（右键）+ Stats（监控）
- 优点：最省事，每个都是成熟产品
- 缺点：没有统一入口，知识类内容（快捷键、配置路径、命令片段）无处安放，也没法跨设备看

> **我的建议：B + C 一起。** 底层能力用现成 App（稳定、不用维护），上层「统一入口 + 知识库 + 本机控制台」用工作台。两者互补，不冲突。

---

## 6. 安全边界（我按这个标准做，也请你知悉）

1. bridge **只监听 `127.0.0.1`**，不对外暴露，局域网内其他机器访问不到
2. **不提供「执行任意命令」接口** —— 只有固定的几个白名单动作（读服务、启停服务、open、lsof、df）
3. 所有路径参数做合法性校验，且拒绝 `..` 穿越
4. 页面若部署到线上，链接是公网可访问的（拿到链接的人能打开页面），但**数据只在你自己浏览器的 localStorage 里，不上服务器**
5. 不会在页面里预填任何真实敏感数据（密码、密钥、token）

---

## 7. 现有技能/专家检索结论（用了你挂的「找技能」）

在 SkillHub 用 `mac` / `macos` / `brew` / `系统工具` 检索了一遍，**没有匹配「Mac 工具管理台」的现成技能**，最接近的只有一个 `MacOCR`（macOS 图片转文字，单功能，不相关）。

结论：**这个工作台没有现成技能可套，得定制做。** 好消息是核心链路我已经实测跑通，不存在技术风险。

---

## 8. 下一步，等你拍板

**问你三件事：**

1. **架构走哪个？** 我推荐 **B（网页 + 本地 bridge）**，理由：你点名的「服务状态」「指定目录开终端」「一键直达」三个核心需求，只有 B 能真正做出来，A 只能做一半。
2. **首版做哪 3-4 个模块？** 我的建议：
   - ① **今天要处理 / 服务控制台**（服务状态 + 一键启停 + 端口速查）—— 你最高频
   - ② **一键直达**（配置/目录卡片：编辑、Finder 显示、在此开终端）—— 你点名要的
   - ③ **快捷键速查**（分类 + 搜索 + 收藏）
   - ④ **命令片段库**（点击复制）
3. **要不要顺手把 T0 工具装上？** 我可以一条命令批量装上 Raycast + Rectangle + Maccy + Stats + Alt-Tab + iTerm2（都是免费的）。装完要手动去系统设置里给权限，我会把步骤写清楚。

你回一句「按你说的来」或者直接点模块，我就开工。
