/**
 * 创建项目页 (C3 project-mgmt, US-2.1)
 *
 * UX 重设(与详情页视觉一致):
 *  - Breadcrumb + 标题 + 副标题(同 ProjectDetailPage)
 *  - "基本信息"分区 Card,内含 name(全宽)+ 编号/限价(Col 12/12 两列)+ 描述(全宽)
 *  - "提示"分区 Card,含未设限价时的维度跳过提醒(不挤在字段里)
 *  - 底部 action bar:取消(左/次) + 创建项目(右/主),卡内对齐详情页的右主 CTA 习惯
 *
 * 业务契约 0 变动,L1 test data-testid 全保留
 */
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Col,
  Form,
  Input,
  Row,
  Space,
  Typography,
} from "antd";
import { ApiError, api } from "../../services/api";

function validateMaxPrice(raw: string): string | null {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  if (!Number.isFinite(n)) return "最高限价必须是数字";
  if (n < 0) return "最高限价不能为负数";
  if (/\.\d{3,}$/.test(raw.trim())) return "最高限价最多保留两位小数";
  return null;
}

export default function ProjectCreatePage() {
  const [name, setName] = useState("");
  const [bidCode, setBidCode] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  const showNoPriceHint = useMemo(() => maxPrice.trim() === "", [maxPrice]);

  async function onSubmit(e: React.SyntheticEvent) {
    e.preventDefault();
    setError(null);

    if (name.trim() === "") {
      setError("项目名称不能为空");
      return;
    }
    if (name.length > 100) {
      setError("项目名称不能超过 100 字符");
      return;
    }
    if (bidCode.length > 50) {
      setError("招标编号不能超过 50 字符");
      return;
    }
    if (description.length > 500) {
      setError("项目描述不能超过 500 字符");
      return;
    }
    const priceError = validateMaxPrice(maxPrice);
    if (priceError) {
      setError(priceError);
      return;
    }

    setSubmitting(true);
    try {
      const created = await api.createProject({
        name: name.trim(),
        bid_code: bidCode.trim() || null,
        max_price: maxPrice.trim() === "" ? null : maxPrice.trim(),
        description: description.trim() || null,
      });
      navigate(`/projects/${created.id}`, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`创建失败 (${err.status})`);
      } else {
        setError("创建失败,请稍后重试");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ maxWidth: 880 }}>
      <Breadcrumb
        items={[
          { title: <Link to="/projects" data-testid="back-to-list">项目</Link> },
          { title: "新建项目" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <div style={{ marginBottom: 20 }}>
        <Typography.Title level={3} style={{ margin: 0, fontWeight: 600, fontSize: 22 }}>
          新建检测项目
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0", fontSize: 13 }}>
          填写项目基础信息;创建后可在详情页添加投标人、上传文件并启动检测
        </Typography.Paragraph>
      </div>

      <Form
        layout="vertical"
        onSubmitCapture={onSubmit}
        component="form"
        data-testid="create-form"
        requiredMark={false}
        size="large"
      >
        {/* 基本信息分区 */}
        <Card
          variant="outlined"
          styles={{ body: { padding: 24 } }}
          style={{ marginBottom: 16 }}
        >
          <Typography.Title
            level={5}
            style={{ margin: "0 0 16px", fontWeight: 600 }}
          >
            基本信息
          </Typography.Title>

          {/* 项目名称 —— 主字段,全宽 */}
          <Form.Item
            label={
              <span>
                项目名称 <span style={{ color: "#c53030" }}>*</span>
              </span>
            }
            extra="用于在列表和报告中识别项目,最长 100 字符"
          >
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              placeholder="如:2026 年高速公路养护项目"
              data-testid="create-name"
              required
              showCount
            />
          </Form.Item>

          {/* 短字段并排 —— 编号 + 限价 */}
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item label="招标编号" extra="选填,最长 50 字符">
                <Input
                  value={bidCode}
                  onChange={(e) => setBidCode(e.target.value)}
                  maxLength={50}
                  placeholder="如:ZB-2026-0001"
                  data-testid="create-bid-code"
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                label="最高限价(元)"
                extra="选填,最多保留两位小数;用于后续报价超限检测"
              >
                <Input
                  value={maxPrice}
                  onChange={(e) => setMaxPrice(e.target.value)}
                  placeholder="如:1000000.00"
                  inputMode="decimal"
                  data-testid="create-max-price"
                />
              </Form.Item>
            </Col>
          </Row>

          {/* 项目描述 —— 长文本,全宽 */}
          <Form.Item label="项目描述" extra="选填,最长 500 字符" style={{ marginBottom: 0 }}>
            <Input.TextArea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
              rows={4}
              placeholder="可填写招标内容、范围、时间要求等"
              data-testid="create-description"
              showCount
            />
          </Form.Item>
        </Card>

        {/* 提示区(条件显示):未设限价 */}
        {showNoPriceHint ? (
          <Alert
            type="warning"
            data-testid="no-max-price-hint"
            showIcon
            message="未设置最高限价,将跳过'报价接近限价'维度检测"
            description="若需启用该维度,请在此页填入最高限价,或稍后在项目详情页补填。"
            style={{ marginBottom: 16 }}
          />
        ) : null}

        {/* 全局错误 */}
        {error ? (
          <Alert
            type="error"
            message={error}
            data-testid="create-error"
            role="alert"
            showIcon
            style={{ marginBottom: 16 }}
          />
        ) : null}

        {/* 底部操作条(卡底对齐详情页风格) */}
        <Card variant="outlined" styles={{ body: { padding: "14px 20px" } }}>
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: 8,
              alignItems: "center",
            }}
          >
            <Typography.Text
              type="secondary"
              style={{ fontSize: 12, marginRight: "auto" }}
            >
              带 <span style={{ color: "#c53030" }}>*</span> 的字段为必填项
            </Typography.Text>
            <Link to="/projects">
              <Button disabled={submitting}>取消</Button>
            </Link>
            <Button
              type="primary"
              htmlType="submit"
              loading={submitting}
              data-testid="create-submit"
            >
              {submitting ? "创建中..." : "创建项目"}
            </Button>
          </div>
        </Card>
      </Form>
    </div>
  );
}

// 留占位避免 "Space 已声明但未使用" 告警(可扩展用)
void Space;
