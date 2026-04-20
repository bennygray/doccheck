/**
 * C15 ExportButton — antd 化:触发 Word 导出 + 进度条 + 重试
 *
 * SSE 契约同原版:event export_progress,data { job_id, phase, progress, message }
 */
import { useEffect, useRef, useState } from "react";
import { Button, Progress, Space, Typography } from "antd";
import {
  CheckCircleFilled,
  CloseCircleFilled,
  DownloadOutlined,
  FileWordOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import { ApiError, api } from "../../services/api";
import { authStorage } from "../../contexts/AuthContext";

type Phase = "idle" | "running" | "done" | "failed";

interface ExportProgressEvent {
  job_id: number;
  phase: "rendering" | "writing" | "done" | "failed";
  progress: number;
  message: string;
}

interface Props {
  projectId: number | string;
  version: number | string;
}

export function ExportButton({ projectId, version }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  const start = async () => {
    setPhase("running");
    setProgress(0);
    setMessage("提交任务");
    try {
      const { job_id } = await api.startExport(projectId, version);
      setJobId(job_id);
      subscribeSse(job_id);
    } catch (err) {
      setPhase("failed");
      setMessage(
        err instanceof ApiError ? `启动失败 (${err.status})` : "启动失败",
      );
    }
  };

  const subscribeSse = (job_id: number) => {
    const urlBase = api.analysisEventsUrl(projectId);
    const token = authStorage.getToken();
    const url = token
      ? `${urlBase}?access_token=${encodeURIComponent(token)}`
      : urlBase;
    const es = new EventSource(url, { withCredentials: false });
    esRef.current = es;

    es.addEventListener("export_progress", (e: MessageEvent) => {
      try {
        const data: ExportProgressEvent = JSON.parse(e.data);
        if (data.job_id !== job_id) return;
        setProgress(data.progress);
        setMessage(data.message);
        if (data.phase === "done") {
          setPhase("done");
          es.close();
          window.open(api.downloadExportUrl(job_id), "_blank");
        } else if (data.phase === "failed") {
          setPhase("failed");
          es.close();
        }
      } catch {
        // ignore
      }
    });
    es.onerror = () => {
      // 简单处理:保留 running 态
    };
  };

  const retry = () => {
    esRef.current?.close();
    setJobId(null);
    void start();
  };

  if (phase === "idle") {
    return (
      <Button type="primary" icon={<FileWordOutlined />} onClick={start}>
        导出 Word
      </Button>
    );
  }

  if (phase === "running") {
    return (
      <Space size={10} align="center">
        <Progress
          percent={Math.round(progress * 100)}
          size="small"
          showInfo={false}
          strokeColor="#1d4584"
          trailColor="#e4e7ed"
          style={{ width: 160 }}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {message}
        </Typography.Text>
      </Space>
    );
  }

  if (phase === "done") {
    return (
      <Space size={8} align="center">
        <CheckCircleFilled style={{ color: "#2d7a4a" }} />
        <Typography.Text style={{ fontSize: 13, color: "#2d7a4a" }}>
          已生成
        </Typography.Text>
        {jobId !== null && (
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            href={api.downloadExportUrl(jobId)}
            target="_blank"
            rel="noreferrer"
            style={{ background: "#2d7a4a", borderColor: "#2d7a4a" }}
          >
            重新下载
          </Button>
        )}
      </Space>
    );
  }

  return (
    <Space size={8} align="center">
      <CloseCircleFilled style={{ color: "#c53030" }} />
      <Typography.Text type="danger" style={{ fontSize: 13 }}>
        {message || "生成失败"}
      </Typography.Text>
      <Button danger icon={<ReloadOutlined />} onClick={retry}>
        重试
      </Button>
    </Space>
  );
}

export default ExportButton;
