/**
 * SkillPanel 组件
 *
 * Skills 管理面板
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { getApiBase } from "../../utils/env";

type SkillItem = {
  name: string;
  description: string;
  source: "local" | "project" | "marketplace";
  version: string;
  author: string;
  tags: string[];
  allowed_tools: string[];
};

type InstalledPluginItem = {
  plugin_name: string;
  marketplace: string;
  spec: string;
  version: string;
  installed_at: string;
  git_commit?: string | null;
  skills: string[];
};

type MarketplaceItem = {
  name: string;
  url: string;
  install_location: string;
  last_updated?: string | null;
};

type SkillDetail = SkillItem & {
  content: string;
  file_path: string;
};

type LoadState = "idle" | "loading" | "success" | "error";

const SOURCE_LABEL: Record<SkillItem["source"], string> = {
  local: "本地",
  project: "项目",
  marketplace: "市场",
};

export function SkillPanel() {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [plugins, setPlugins] = useState<InstalledPluginItem[]>([]);
  const [marketplaces, setMarketplaces] = useState<MarketplaceItem[]>([]);
  const [search, setSearch] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<SkillDetail | null>(null);
  const [listState, setListState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [actionTarget, setActionTarget] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [showMarketplaces, setShowMarketplaces] = useState(false);

  const apiBase = getApiBase();
  const apiPrefix = apiBase ? apiBase : "";

  const installedSkillMap = useMemo(() => {
    const map = new Map<string, InstalledPluginItem>();
    plugins.forEach((plugin) => {
      plugin.skills.forEach((skill) => {
        if (!map.has(skill)) {
          map.set(skill, plugin);
        }
      });
    });
    return map;
  }, [plugins]);

  const filteredSkills = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return skills;
    return skills.filter((skill) => {
      const haystack = [
        skill.name,
        skill.description,
        skill.author,
        skill.tags.join(" "),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [skills, search]);

  const fetchMarketplaces = useCallback(async () => {
    try {
      const response = await fetch(`${apiPrefix}/api/skills/marketplace/list`);
      if (response.ok) {
        const data = await response.json();
        setMarketplaces(data.marketplaces || []);
      }
    } catch (error) {
      console.error("获取 marketplaces 失败:", error);
    }
  }, [apiPrefix]);

  const fetchSkills = useCallback(async () => {
    setListState("loading");
    try {
      const [skillsRes, pluginsRes] = await Promise.all([
        fetch(`${apiPrefix}/api/skills`),
        fetch(`${apiPrefix}/api/skills/installed`),
      ]);

      if (!skillsRes.ok) {
        throw new Error("获取 skills 失败");
      }
      if (!pluginsRes.ok) {
        throw new Error("获取已安装插件失败");
      }

      const skillsData = await skillsRes.json();
      const pluginsData = await pluginsRes.json();
      setSkills(skillsData.skills || []);
      setPlugins(pluginsData.plugins || []);
      setListState("success");

      fetchMarketplaces();
    } catch (error) {
      console.error(error);
      setListState("error");
    }
  }, [apiPrefix, fetchMarketplaces]);

  const fetchSkillDetail = useCallback(
    async (skillName: string) => {
      setDetailState("loading");
      try {
        const response = await fetch(
          `${apiPrefix}/api/skills/${encodeURIComponent(skillName)}`
        );
        if (!response.ok) {
          throw new Error("获取 skill 详情失败");
        }
        const data = await response.json();
        setSelectedSkill(data);
        setDetailState("success");
      } catch (error) {
        console.error(error);
        setDetailState("error");
      }
    },
    [apiPrefix]
  );

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  const handleOpenSkill = useCallback(
    (skillName: string) => {
      fetchSkillDetail(skillName);
    },
    [fetchSkillDetail]
  );

  const handleBackToList = useCallback(() => {
    setSelectedSkill(null);
    setDetailState("idle");
  }, []);

  const handleInstall = useCallback(
    async (skillName?: string) => {
      const marketplaceNames = marketplaces.map((m) => m.name).join(", ");
      const defaultSpec = skillName
        ? `${skillName}@anthropics`
        : "plugin-name@anthropics";
      const hint = marketplaceNames
        ? `可用 marketplace: ${marketplaceNames}`
        : "默认 marketplace: anthropics";
      const spec = window.prompt(
        `请输入插件规格 (plugin@marketplace)\n${hint}`,
        defaultSpec
      );
      if (!spec) return;

      setActionTarget(spec);
      setMessage(null);
      try {
        const response = await fetch(`${apiPrefix}/api/skills/install`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ spec, force: false }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
          throw new Error(data.detail || data.message || "安装失败");
        }
        setMessage(`已安装：${spec}`);
        await fetchSkills();
        if (selectedSkill) {
          await fetchSkillDetail(selectedSkill.name);
        }
      } catch (error) {
        console.error(error);
        setMessage("安装失败，请检查插件规格或网络");
      } finally {
        setActionTarget(null);
      }
    },
    [apiPrefix, fetchSkills, fetchSkillDetail, selectedSkill, marketplaces]
  );

  const handleImportLocal = useCallback(async () => {
    const path = window.prompt(
      "请输入服务端本地 skill 路径（SKILL.md 或目录）"
    );
    if (!path) return;

    setActionTarget("import_local");
    setMessage(null);
    try {
      const response = await fetch(`${apiPrefix}/api/skills/import_local`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, force: false }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.detail || data.message || "导入失败");
      }
      setMessage(`已导入：${data.skill?.name || path}`);
      await fetchSkills();
      if (data.skill?.name) {
        await fetchSkillDetail(data.skill.name);
      }
    } catch (error) {
      console.error(error);
      setMessage("导入失败，请检查路径或权限");
    } finally {
      setActionTarget(null);
    }
  }, [apiPrefix, fetchSkills, fetchSkillDetail]);

  const handleAddMarketplace = useCallback(async () => {
    const name = window.prompt(
      "请输入 Marketplace 名称（用于安装时引用，如 'baoyu'）:",
      ""
    );
    if (!name) return;

    const url = window.prompt(
      "请输入 Git 仓库 URL（如 'https://github.com/JimLiu/baoyu-skills'）:",
      ""
    );
    if (!url) return;

    setMessage(null);
    try {
      const response = await fetch(`${apiPrefix}/api/skills/marketplace/add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, url }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.detail || data.message || "添加失败");
      }
      setMessage(`已添加 Marketplace: ${name} (${url})`);
      await fetchMarketplaces();
    } catch (error) {
      console.error(error);
      setMessage("添加 Marketplace 失败，请检查 URL 是否正确");
    }
  }, [apiPrefix, fetchMarketplaces]);

  const handleUninstall = useCallback(
    async (spec: string) => {
      if (!spec) return;
      const confirmed = window.confirm(`确认卸载 ${spec} ?`);
      if (!confirmed) return;

      setActionTarget(spec);
      setMessage(null);
      try {
        const response = await fetch(`${apiPrefix}/api/skills/uninstall`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ spec }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
          throw new Error(data.detail || data.message || "卸载失败");
        }
        setMessage(`已卸载：${spec}`);
        await fetchSkills();
        if (selectedSkill) {
          await fetchSkillDetail(selectedSkill.name);
        }
      } catch (error) {
        console.error(error);
        setMessage("卸载失败，请稍后重试");
      } finally {
        setActionTarget(null);
      }
    },
    [apiPrefix, fetchSkills, fetchSkillDetail, selectedSkill]
  );

  const renderActionButton = (skill: SkillItem) => {
    const plugin = installedSkillMap.get(skill.name);
    if (plugin) {
      const isLoading = actionTarget === plugin.spec;
      return (
        <button
          onClick={(event) => {
            event.stopPropagation();
            handleUninstall(plugin.spec);
          }}
          className={`px-3 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap ${
            isLoading
              ? "bg-secondary text-text-muted cursor-not-allowed"
              : "bg-danger text-white hover:bg-danger/90"
          }`}
          disabled={isLoading}
        >
          卸载
        </button>
      );
    }

    if (skill.source === "marketplace") {
      const isLoading = actionTarget === `${skill.name}@anthropics`;
      return (
        <button
          onClick={(event) => {
            event.stopPropagation();
            handleInstall(skill.name);
          }}
          className={`px-3 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap ${
            isLoading
              ? "bg-secondary text-text-muted cursor-not-allowed"
              : "bg-accent text-white hover:bg-accent-hover"
          }`}
          disabled={isLoading}
        >
          安装
        </button>
      );
    }

    return (
      <button
        className="px-3 py-1.5 rounded-md text-sm bg-secondary text-text-muted cursor-not-allowed whitespace-nowrap"
        disabled
      >
        内置
      </button>
    );
  };

  const renderStatus = (skill: SkillItem) => {
    const plugin = installedSkillMap.get(skill.name);
    if (plugin) return "已安装";
    if (skill.source === "marketplace") return "未安装";
    return "内置";
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0">
      <div className="card flex-1 flex flex-col min-h-0 overflow-hidden">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-lg font-semibold text-text-strong">
              Skills 管理
            </div>
            <p className="text-sm text-text-muted">
              管理并安装 Agent 可用的 Skills。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchSkills}
              className="px-3 py-1.5 rounded-md text-sm bg-secondary text-text-muted hover:text-text hover:bg-card border border-border"
            >
              刷新
            </button>
            <button
              onClick={handleImportLocal}
              className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                actionTarget === "import_local"
                  ? "bg-secondary text-text-muted cursor-not-allowed"
                  : "bg-secondary text-text hover:bg-card border border-border"
              }`}
              disabled={actionTarget === "import_local"}
            >
              导入本地 skill
            </button>
            <button
              onClick={() => setShowMarketplaces(!showMarketplaces)}
              className="px-3 py-1.5 rounded-md text-sm bg-secondary text-text-muted hover:text-text hover:bg-card border border-border"
            >
              {showMarketplaces ? "隐藏 Marketplace" : "Marketplace"}
            </button>
            <button
              onClick={handleAddMarketplace}
              className="px-3 py-1.5 rounded-md text-sm bg-secondary text-text-muted hover:text-text hover:bg-card border border-border"
            >
              添加源
            </button>
            <button
              onClick={() => handleInstall()}
              className="px-3 py-1.5 rounded-md text-sm bg-accent text-white hover:bg-accent-hover"
            >
              安装插件
            </button>
          </div>
        </div>

        {message && (
          <div className="mt-3 px-3 py-2 rounded-md bg-secondary text-sm text-text">
            {message}
          </div>
        )}

        {showMarketplaces && (
          <div className="mt-3 p-3 rounded-lg border border-border bg-panel">
            <div className="text-sm font-medium text-text mb-2">
              已配置的 Marketplace（{marketplaces.length} 个）
            </div>
            {marketplaces.length === 0 ? (
              <div className="text-xs text-text-muted">
                暂无自定义 Marketplace，点击"添加源"添加
              </div>
            ) : (
              <div className="space-y-2">
                {marketplaces.map((mp) => (
                  <div
                    key={mp.name}
                    className="flex items-center justify-between p-2 rounded-md bg-secondary text-xs"
                  >
                    <div>
                      <span className="font-medium text-text">{mp.name}</span>
                      <span className="text-text-muted ml-2">{mp.url}</span>
                    </div>
                    {mp.last_updated && (
                      <span className="text-text-muted">
                        更新于 {new Date(mp.last_updated).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="mt-2 text-xs text-text-muted">
              安装示例：添加 baoyu marketplace 后，使用{" "}
              <code className="px-1 py-0.5 bg-card rounded">
                baoyu-comic@baoyu
              </code>{" "}
              安装插件
            </div>
          </div>
        )}

        {selectedSkill ? (
          <div className="mt-4 flex-1 overflow-y-auto">
            <div className="flex items-center gap-2 mb-3">
              <button
                onClick={handleBackToList}
                className="px-3 py-1.5 rounded-md text-sm bg-secondary text-text-muted hover:text-text hover:bg-card border border-border"
              >
                返回列表
              </button>
              <div className="text-sm text-text-muted">
                {detailState === "loading" && "加载详情中..."}
                {detailState === "error" && "加载详情失败"}
              </div>
            </div>

            <div className="rounded-lg border border-border bg-panel p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-lg font-semibold text-text-strong">
                    {selectedSkill.name}
                  </div>
                  <div className="text-sm text-text-muted mt-1">
                    {selectedSkill.description || "暂无描述"}
                  </div>
                  <div className="flex flex-wrap gap-2 mt-3 text-xs text-text-muted">
                    <span className="px-2 py-1 rounded-full bg-secondary border border-border">
                      来源：{SOURCE_LABEL[selectedSkill.source]}
                    </span>
                    <span className="px-2 py-1 rounded-full bg-secondary border border-border">
                      版本：{selectedSkill.version || "unknown"}
                    </span>
                    <span className="px-2 py-1 rounded-full bg-secondary border border-border">
                      作者：{selectedSkill.author || "unknown"}
                    </span>
                  </div>
                </div>

                <div className="flex flex-col items-end gap-2">
                  <span className="text-xs text-text-muted">
                    {renderStatus(selectedSkill)}
                  </span>
                  {renderActionButton(selectedSkill)}
                </div>
              </div>

              <div className="mt-4">
                <div className="text-sm font-medium text-text mb-2">
                  允许工具
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-text-muted">
                  {selectedSkill.allowed_tools?.length ? (
                    selectedSkill.allowed_tools.map((tool) => (
                      <span
                        key={tool}
                        className="px-2 py-1 rounded-full bg-secondary border border-border"
                      >
                        {tool}
                      </span>
                    ))
                  ) : (
                    <span className="text-text-muted">无限制</span>
                  )}
                </div>
              </div>

              <div className="mt-4">
                <div className="text-sm font-medium text-text mb-2">
                  内容预览
                </div>
                <div className="text-sm text-text whitespace-pre-wrap bg-secondary border border-border rounded-md p-3">
                  {selectedSkill.content || "暂无内容"}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-4 flex flex-col flex-1 min-h-0">
            <div className="flex items-center gap-3 flex-shrink-0">
              <div className="flex-1 min-w-0">
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="搜索 skill 名称、描述或标签"
                  className="w-full px-3 py-2 rounded-md bg-panel border border-border text-sm text-text placeholder:text-text-muted"
                />
              </div>
              <div className="text-xs text-text-muted flex-shrink-0">
                共 {filteredSkills.length} 个
              </div>
            </div>

            <div className="mt-4 flex-1 min-h-0 overflow-y-auto space-y-3">
              {listState === "loading" && (
                <div className="text-sm text-text-muted">加载中...</div>
              )}
              {listState === "error" && (
                <div className="text-sm text-text-muted">
                  获取 skills 失败，请检查后端服务
                </div>
              )}
              {listState === "success" && filteredSkills.length === 0 && (
                <div className="text-sm text-text-muted">暂无匹配的技能</div>
              )}
                {listState === "success" &&
                filteredSkills.map((skill) => (
                  <button
                    key={skill.name}
                    onClick={() => handleOpenSkill(skill.name)}
                    className="w-full text-left p-4 rounded-lg border border-border bg-panel hover:bg-card transition-colors"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="text-base font-semibold text-text-strong">
                          {skill.name}
                        </div>
                        <div className="text-sm text-text-muted mt-1 line-clamp-3">
                          {skill.description || "暂无描述"}
                        </div>
                        <div className="flex flex-wrap gap-2 mt-3 text-xs text-text-muted">
                          <span className="px-2 py-1 rounded-full bg-secondary border border-border">
                            来源：{SOURCE_LABEL[skill.source]}
                          </span>
                          <span className="px-2 py-1 rounded-full bg-secondary border border-border">
                            状态：{renderStatus(skill)}
                          </span>
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-2 flex-shrink-0">
                        {renderActionButton(skill)}
                      </div>
                    </div>
                  </button>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
