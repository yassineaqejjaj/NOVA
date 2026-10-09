"use client";

import { Badge, Button, Input, Label, Select } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api/client";
import { engKeys, type LlmConfig, useLlmConfig } from "@/lib/api/engineering";
import { useT } from "@/lib/i18n";

import { M } from "./engineering.messages";

/** Settings → AI model: bring your own LLM API key (encrypted, tested before it is saved). */
export function LlmSettings() {
  const t = useT(M);
  const client = useQueryClient();
  const { data } = useLlmConfig();
  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [key, setKey] = useState("");
  const [ack, setAck] = useState(false);

  useEffect(() => {
    if (!data) return;
    const p = data.provider ?? "anthropic";
    setProvider(p);
    setModel(data.model ?? data.providers.find((x) => x.id === p)?.default_model ?? "");
    setBaseUrl(data.base_url);
  }, [data]);

  const save = useMutation({
    mutationFn: () => api.put<LlmConfig>("/me/llm", { provider, model, api_key: key || null, base_url: baseUrl, acknowledge_data_sharing: ack }),
    onSuccess: (next) => {
      client.setQueryData(engKeys.llm, next);
      setKey("");
      setAck(false);
      toast(t("llmSaved"));
    },
  });
  const test = useMutation({ mutationFn: () => api.post("/me/llm/test"), onSuccess: () => toast(t("llmTestOk")) });
  const remove = useMutation({
    mutationFn: () => api.delete("/me/llm"),
    onSuccess: () => {
      toast(t("llmRemoved"));
      void client.invalidateQueries({ queryKey: engKeys.llm });
    },
  });

  if (!data) return null;
  const info = data.providers.find((p) => p.id === provider);
  const err = (e: unknown) => (e instanceof ApiError ? <p role="alert" className="text-[13px] text-danger">{e.message}</p> : null);
  const choose = (value: string) => {
    setProvider(value);
    setModel(data.providers.find((p) => p.id === value)?.default_model ?? "");
    setAck(false);
  };
  const keyStored = data.configured && data.provider === provider;
  const canSave = (key.trim().length > 0 || keyStored) && ack && model.trim().length > 0 && (!info?.needs_base_url || baseUrl.trim().length > 0);

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSave) save.mutate();
      }}
    >
      {data.configured ? (
        <div className="flex flex-wrap items-center gap-2 text-[13.5px]">
          <span className="size-2 rounded-full bg-success" aria-hidden />
          {t("llmActive", { provider: data.providers.find((p) => p.id === data.provider)?.label ?? data.provider, model: data.model })}
          <Badge tone="success">····{data.key_hint || "key"}</Badge>
          <Button type="button" variant="ghost" size="sm" onClick={() => test.mutate()} disabled={test.isPending} className="ml-auto">{t("llmTest")}</Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => remove.mutate()} disabled={remove.isPending}>{t("llmRemove")}</Button>
        </div>
      ) : (
        <p className="text-[12.5px] text-subtle">{t("llmDefault", { model: data.default_model || "—" })}</p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>{t("llmProvider")}</Label>
          <Select value={provider} onValueChange={choose} options={data.providers.map((p) => ({ value: p.id, label: p.label }))} className="w-full" ariaLabel={t("llmProvider")} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="llm-model">{t("llmModel")}</Label>
          <Input id="llm-model" value={model} onChange={(e) => setModel(e.target.value)} list="llm-models" autoComplete="off" />
          <datalist id="llm-models">{info?.models.map((m) => <option key={m} value={m} />)}</datalist>
        </div>
        {info?.needs_base_url ? (
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="llm-url">{t("llmBaseUrl")}</Label>
            <Input id="llm-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" autoComplete="off" />
          </div>
        ) : null}
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="llm-key">{t("llmKey")}</Label>
          <Input
            id="llm-key"
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
            placeholder={keyStored ? t("llmKeyKeep", { hint: data.key_hint }) : info?.key_hint || ""}
          />
        </div>
      </div>
      <label className="flex items-start gap-2.5 rounded-[12px] border border-warning/30 bg-warning/[0.06] px-3 py-2.5 text-[12.5px] text-muted">
        <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5" />
        <span><AlertTriangle className="mr-1 inline size-3.5 text-warning" aria-hidden />{t("llmAck")}</span>
      </label>
      {err(save.error)}
      {err(test.error)}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" size="sm" disabled={!canSave || save.isPending}>{t("llmSave")}</Button>
      </div>
    </form>
  );
}
