# SAM 2.1 Tiny / YOLO11n 真实验证

2026-10-22，AnnoDesk 0.2.0。此记录使用真实本地权重、生产适配器、CLI、HTTP API 和浏览器工作台；推理结果未使用合成 mask 或假适配器替代。自动化回归测试中的假适配器仅用于协议测试。

## 环境与样本

- macOS 26.5，Apple M2 Max，32 GiB RAM，12 CPU 核；Python 3.13.3。
- 隔离环境：Torch 2.14.1、Torchvision 0.29.1、Ultralytics 8.4.183、NumPy 2.5.4、OpenCV 5.0.0.93。
- SAM：`facebook/sam2.1-hiera-tiny`，通过 `HF_MODELS` 解析到本地目录，加载 Meta `sam2.1_hiera_tiny.pt`，未下载权重。
- 检测：用户指定的本地 `yolo11n.pt`；测试模型目录只有一个指向该文件的符号链接。直接读取 checkpoint 的80类表，未用 sidecar 覆盖。
- SAM SHA256：`7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69`。
- YOLO SHA256：`0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`。

从 [Ultralytics COCO128](https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip) 下载样本包，固定间隔选取其中16张 COCO train2017 图片及原始 YOLO 标签。图片 ID（前缀补齐为12位）：9、64、89、136、165、250、312、349、389、428、472、510、544、584、623、650。覆盖食物、室内、人物、动物、火车、街景、远处飞机和拥挤运动场景；共97个原始检测框，1张没有框。

测试使用互相独立的项目副本。原始样本、模型、截图和逐次运行记录不进入 Git。完整本机证据保存在忽略目录 `docs/design-previews/real-validation/`，含 manifest、模型配置、脚本、JSON 报告、日志和截图；这些临时验证脚本中的路径指向本次 `/tmp/annodesk-real-validation/` 工作目录。

## 实测结果

| 路径 | 结果 |
| --- | --- |
| CPU / MPS 适配器 | 两种设备均完成单点、正负点、框、框加点、单/多掩码调用，返回原图尺寸 |
| 16图提示矩阵 / MPS | 每图正点、正负点、框、框加正负点，各测单/多掩码，共128次；124次返回有效 mask，4次未返回有效 mask |
| CLI 检测 / CPU 2 workers | 16/16成功，新增76个框、25个实际出现的类别；允许空结果，自动结果仍为pending |
| 原始框 CLI 分割 / MPS | 修复边界舍入后累计15张有框图全部成功，97个框各有一个mask；1张无框跳过。1 worker全量及2 workers重跑失败项均实测 |
| YOLO框 → SAM / HTTP任务 | 15张有检测结果的图成功，1张无框跳过；MPS双worker，76个mask，全部保持未审核 |
| 页面启动批量 / MPS 2 workers | 预检16张：Excluded 1、非目标审核状态2、无可处理对象1，实际12/12成功、0失败；锁定实例保持无mask |
| 取消 / 恢复 | 取消时2张已保存、13张剩余；原任务恢复后累计15张成功、0失败，1张无框跳过 |
| 类别校验 | checkpoint类别可读；项目子集兼容；ID 0 的cat与模型person冲突时报400；无任何可接受类别时预检400 |
| 类别筛选 / 新类别开关 | 关闭时丢弃项目外检测；开启后仅增加实际识别的cat ID15，保留person ID0，不创建未用类别 |
| 检测追加 | MPS真实检测与已有同类框去重，本例6→6，未重复追加 |
| 候选保存保护 | 真实候选按质量排序；生成前后标注文件字节一致；修改revision后Apply返回409；隐藏/锁定返回400 |
| 文本能力 | SAM2文本分割和文本候选均拒绝，未伪装支持语言提示 |
| 导出 | pending显式纳入的YOLO检测、YOLO分割、COCO分割均完成；排除图片跳过；工作类别保持稀疏ID |
| 审核统计 | 人工设置后16张显示pending14、Approved1、Excluded1、Reviewed2；关闭任务窗口后统计仍在 |

128次矩阵中有效输出数量分布为：0个4次、1个65次、2个15次、3个44次。无有效输出来自图片428、584的正负点组合，单、多掩码各一次。提示点由原始框中心和框角附近确定，可能没有落在目标内部或排除了目标；这是模型输出，不能承诺每组提示恰好返回3个候选。真实HTTP复验中，候选和单掩码接口均对空输出返回400，已有标注文件字节不变。

浏览器实际操作（英文与中文）包括：

- 猫图正点、背景负点、生成候选、切换候选、取消和应用；mask-only阶段不产生检测框。
- 大象图手画框提示，Segment current保存mask，检测labels为空。
- 手动画火车检测框、数值调整x1至20、类别面板换类、框引导单mask、删除与撤销、人工Approved、切图自动保存。
- 从mask显式生成框；处理期间立即改类会触发并发编辑保护，不能覆盖较新的编辑。
- 页面YOLO检测食物图得到6个可编辑框；开启Auto-segment，切出后切回得到6个mask。
- 页面启动真实批量、查看完成计数、收起/再打开Tasks、常驻审核统计；日志包含真实模型、MPS、2 workers READY及完成事件。

## 发现并修复

1. Meta官方SAM2文件名不符合Ultralytics自动分派命名：对明确的官方Hiera文件名选择相应构建器，读取原本地路径。实测Tiny；其他架构映射不等于已实测。
2. 正负点使用平面数组被解释成多个对象，框加多个点报张量尺寸错误：传入`[1,N,2]`点和`[1,N]`标签，明确细化同一实例。修复后重跑全部矩阵与HTTP候选保护测试。
3. 批次协调者及worker把解析后权重的父目录当模型目录，导致符号链接指向含多个权重的目录时出错：冻结配置解析出的原模型目录。
4. COCO六位小数框的边界出现0.000128～0.000240像素越界，保存失败：容忍最大图像边长`1e-6`倍的舍入偏差并裁剪到边界，拒绝真实越界和退化框。首次失败3图，修复后双MPS worker均成功。
5. Segment current只补显式box，漏掉点/框提示草稿：当前图补mask包含有提示且无mask的未锁定实例；CLI/批量仍只处理已有检测框。

以上均增加回归测试。97项Python测试、22项前端测试、Ruff及前端构建通过；wheel另做仓库外隔离安装、静态/API/文档检查及真实CPU/MPS推理复验。

## 复现入口

将样本放在`dataset/images/val`，检测框放在`dataset/labels/val`，提供与COCO类别一致的`data.yaml`。配置SAM目录与只有一个检测checkpoint的目录，显式安装推理依赖后：

```sh
annodesk detect --project /absolute/detection-project --models-config /absolute/models.json \
  --model yolo11n --allow-new-classes --device-type cpu --num-workers 2
annodesk segment --project /absolute/box-project --models-config /absolute/models.json \
  --model sam-tiny --device-type mps --num-workers 2
annodesk serve --project /absolute/manual-project --models-config /absolute/models.json
```

每次测试保留`.annodesk/*-report.json`或`.annodesk/jobs/*.json`，重复完整实验使用新的项目副本；已有mask按设计跳过。

## 验证边界

这是功能、保存一致性与有限视觉检查，不是COCO mask AP评测；未下载实例分割真值，不能报告IoU/AP或声称分割质量足以直接替代人工审核。128次提示矩阵中的“质量分数”是模型预测分数，不是实测准确率。

已实测本机CPU和MPS，以及同一MPS设备双worker；没有CUDA机器，不推断CUDA、多GPU、其他操作系统或长期压力测试结果。MobileSAM、SAM1、SAM3及语言提示未进行真实权重验证；安装依赖的版本范围不代表范围内所有版本已实测。浏览器类别新增使用原生prompt，本次准备类别通过API完成，未把它记为页面类别新增验收。

## 方向一致性补充回归

在同一隔离环境与本地权重下，取COCO图片9的临时副本，写入EXIF Orientation=6，并生成像素完全相同、去除方向元数据的PNG。使用当前生产适配器在CPU分别处理两份图片：SAM 2.1 Tiny单掩码结果逐像素一致（640×480，41,255个前景像素），YOLO11n均返回7个检测，类别一致，框误差不超过1e-5、置信度误差不超过1e-6。验证BGR ndarray输入绕过二次文件方向处理；本次未新增MPS/CUDA实测，不把方向单测冒充真实模型验证。

另以自动化生成的JPEG/TIFF测试8种EXIF方向，核对预览、缩略图、推理输入与YOLO/COCO导出的像素、尺寸及标注坐标；这些格式回归使用测试数据，不计作新增真实模型样本。TIFF浏览器入口返回PNG，未在本次补充中进行独立浏览器手动验收。
