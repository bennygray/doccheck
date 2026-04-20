/**
 * C15 ReviewPanel — 整报告级人工复核表单(antd 化)
 *
 * - 未复核:显示 status Select + comment TextArea + 提交
 * - 已复核:显示结论 + 修改按钮
 * - 复核不改 total_score / risk_level(D11)
 */
import { useState } from "react";
import {
  Alert,
  Button,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { EditOutlined } from "@ant-design/icons";

import { ApiError, api } from "../../services/api";
import type { ReviewStatus } from "../../types";

const STATUS_OPTIONS: Array<{ value: ReviewStatus; label: string; color: string }> = [
  { value: "confirmed", label: "确认围标", color: "error" },
  { value: "rejected", label: "排除围标", color: "default" },
  { value: "downgraded", label: "降级风险", color: "warning" },
  { value: "upgraded", label: "升级风险", color: "error" },
];

const STATUS_META: Record<ReviewStatus, { label: string; color: string }> =
  Object.fromEntries(STATUS_OPTIONS.map((o) => [o.value, { label: o.label, color: o.color }])) as Record<
    ReviewStatus,
    { label: string; color: string }
  >;

interface Props {
  projectId: number | string;
  version: number | string;
  current: {
    status: ReviewStatus | null;
    comment: string | null;
    reviewer_id: number | null;
    reviewed_at: string | null;
  };
  onSubmitted?: () => void;
}

export function ReviewPanel({ projectId, version, current, onSubmitted }: Props) {
  const [editing, setEditing] = useState(current.status === null);
  const [status, setStatus] = useState<ReviewStatus | "">(current.status ?? "");
  const [comment, setComment] = useState(current.comment ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.SyntheticEvent) => {
    e.preventDefault();
    if (!status) {
      setError("请选择复核结论后再提交");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.postReview(projectId, version, {
        status,
        comment: comment || undefined,
      });
      setEditing(false);
      onSubmitted?.();
    } catch (err) {
      setError(
        err instanceof ApiError ? `提交失败 (${err.status})` : "提交失败",
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (!editing && current.status) {
    const meta = STATUS_META[current.status];
    return (
      <div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: 8,
          }}
        >
          <Space size={8} align="center">
            <Typography.Text style={{ fontSize: 13, color: "#5c6370" }}>
              结论
            </Typography.Text>
            <Tag color={meta.color} style={{ margin: 0, fontWeight: 600 }}>
              {meta.label}
            </Tag>
          </Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => setEditing(true)}
          >
            修改
          </Button>
        </div>
        {current.comment && (
          <Typography.Paragraph
            style={{ fontSize: 13, color: "#5c6370", margin: "4px 0" }}
          >
            评论:{current.comment}
          </Typography.Paragraph>
        )}
        {current.reviewed_at && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {new Date(current.reviewed_at).toLocaleString()} by user#
            {current.reviewer_id}
          </Typography.Text>
        )}
      </div>
    );
  }

  return (
    <Form
      layout="vertical"
      component="form"
      onSubmitCapture={submit}
      requiredMark={false}
    >
      <Form.Item label="复核结论" required>
        <Select
          value={status || undefined}
          onChange={(v) => setStatus(v)}
          placeholder="请选择复核结论"
          disabled={submitting}
          options={STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          style={{ width: 220 }}
        />
      </Form.Item>
      <Form.Item label="评论(可选)">
        <Input.TextArea
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          disabled={submitting}
          placeholder="可填写复核原因或补充说明"
          maxLength={500}
          showCount
        />
      </Form.Item>
      {error && (
        <Alert
          type="error"
          message={error}
          showIcon
          style={{ marginBottom: 12 }}
        />
      )}
      <Space>
        <Button type="primary" htmlType="submit" loading={submitting}>
          {submitting ? "提交中" : "提交复核"}
        </Button>
        {current.status && (
          <Button onClick={() => setEditing(false)} disabled={submitting}>
            取消
          </Button>
        )}
      </Space>
    </Form>
  );
}

export default ReviewPanel;
