#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# analyze.py — consolida os resultados do Trabalho Prático 06.
#
# Entrada (gerada por scripts/run_experiments.sh), diretorio results/raw/:
#   <perfil>_<users>u_rep<k>_stats.csv        (Locust — janela de MEDIÇÃO)
#   <perfil>_<users>u_rep<k>_dockerstats.csv  (CPU/mem via docker stats)
#   <perfil>_<users>u_rep<k>_warmup_*         (AQUECIMENTO — descartado)
#
# Saída:
#   results/tables/resumo_geral.md  / .csv  -> tempo médio, P95, vazão, reqs, falhas
#   results/tables/operacoes.md    / .csv   -> tempo médio e vazão por operação
#   results/tables/cpu_servicos.md / .csv   -> consumo de CPU por serviço
#   results/tables/numeros_chave.md          -> números que respondem às questões
#   results/charts/*.png                     -> gráficos comparativos
#
# O aquecimento é rodado em um processo Locust separado (sufixo `_warmup`),
# então descartá-lo = simplesmente ignorar esses arquivos aqui.
# ---------------------------------------------------------------------------
import re
import sys
import pathlib

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"
TABLES = ROOT / "results" / "tables"
CHARTS = ROOT / "results" / "charts"

SCENARIO_LABEL = {30: "A - Leve (30u)", 80: "B - Moderado (80u)", 150: "C - Elevado (150u)"}
PROFILE_LABEL = {"read": "Perfil 1 (Leitura)", "write": "Perfil 2 (Escrita)"}
STYLE = {"read": "#1f77b4", "write": "#d62728"}
LABEL = {"read": "Perfil 1 - Leitura", "write": "Perfil 2 - Escrita"}
OP_NAMES = {
    "GET /api/customer/owners": "GET /owners",
    "GET /api/customer/owners/{id}": "GET /owners/{id}",
    "GET /api/vet/vets": "GET /vets",
    "POST /api/customer/owners": "POST /owners",
}
METRICS = ["avg_ms", "p95_ms", "rps", "requisicoes", "fail_pct"]
RUN_RE = re.compile(r"(read|write)_(\d+)u_rep(\d+)$")
MEASURED_MINUTES = 6.0


def load_one_stats(run_id: str):
    """Lê o _stats.csv de UMA execução. Retorna (linha agregada, DF por operação)."""
    df = pd.read_csv(RAW / f"{run_id}_stats.csv")
    df = df.rename(columns={
        "Type": "type", "Name": "name", "Request Count": "requests",
        "Failure Count": "failures", "Average Response Time": "avg_ms",
        "95%": "p95_ms", "Requests/s": "rps",
    })
    for col in ("requests", "failures", "avg_ms", "p95_ms", "rps"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    agg = df[df["type"] == "Aggregated"]
    if agg.empty:
        agg = df[df["name"] == "Aggregated"]
    if agg.empty:
        return None, None

    ops = df[df["type"].isin(["GET", "POST"]) & df["name"].isin(OP_NAMES)].copy()
    return agg.iloc[0], ops


def load_one_docker(run_id: str):
    path = RAW / f"{run_id}_dockerstats.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if df.empty:
        return None
    df["cpu_percent"] = pd.to_numeric(
        df["cpu_percent"].astype(str).str.replace("%", "", regex=False).str.strip(),
        errors="coerce",
    )
    return df


def load_all_runs():
    """Varre results/raw/ e devolve (resumo, operacoes, cpu)."""
    resumo_rows, ops_frames, cpu_frames = [], [], []
    run_ids = sorted({
        p.name[: -len("_stats.csv")]
        for p in RAW.glob("*_stats.csv")
        if "_warmup" not in p.name          # <- descarte do aquecimento
    })

    for run_id in run_ids:
        m = RUN_RE.match(run_id)
        if not m:
            print(f"  !! nome fora do padrao, ignorado: {run_id}", file=sys.stderr)
            continue
        profile, users, rep = m.group(1), int(m.group(2)), int(m.group(3))

        agg, ops = load_one_stats(run_id)
        if agg is None:
            print(f"  !! {run_id}: linha 'Aggregated' ausente, ignorado", file=sys.stderr)
            continue

        reqs = float(agg["requests"])
        resumo_rows.append({
            "run_id": run_id,
            "profile": profile,
            "users": users,
            "rep": rep,
            "avg_ms": agg["avg_ms"],
            "p95_ms": agg["p95_ms"],
            "rps": agg["rps"],
            "requisicoes": reqs,
            "fail_pct": (float(agg["failures"]) / reqs * 100.0) if reqs else 0.0,
        })

        if not ops.empty:
            ops["run_id"] = run_id
            ops["profile"] = profile
            ops["users"] = users
            ops["rep"] = rep
            ops["operacao"] = ops["name"].map(OP_NAMES)
            ops_frames.append(ops[["run_id", "profile", "users", "rep",
                                   "operacao", "requests", "failures", "avg_ms"]])

        cpu = load_one_docker(run_id)
        if cpu is not None and not cpu.empty:
            c = cpu.groupby("container")["cpu_percent"].mean().reset_index()
            c["run_id"] = run_id
            c["profile"] = profile
            c["users"] = users
            cpu_frames.append(c)

    resumo = pd.DataFrame(resumo_rows)
    operacoes = pd.concat(ops_frames, ignore_index=True) if ops_frames else pd.DataFrame()
    cpu = pd.concat(cpu_frames, ignore_index=True) if cpu_frames else pd.DataFrame()
    return resumo, operacoes, cpu


def write_table(name: str, title: str, df: pd.DataFrame) -> None:
    """Grava results/tables/<name>.md e .csv."""
    csv_path = TABLES / f"{name}.csv"
    df.to_csv(csv_path, index=False)
    md_path = TABLES / f"{name}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(df.to_markdown(index=False, floatfmt=".2f") + "\n")
    print(f"  tabela -> results/tables/{name}.md (+ .csv)")


def plot_line(source: pd.DataFrame, ycol: str, yerr: str, ylabel: str,
              title: str, fname: str) -> None:
    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    for profile, color in STYLE.items():
        sub = source[source["profile"] == profile].sort_values("users")
        if sub.empty:
            continue
        ax.errorbar(sub["users"], sub[ycol], yerr=sub[yerr],
                    marker="o", capsize=3, color=color, label=LABEL[profile])
    ax.set_xlabel("Usuários virtuais")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xticks(sorted(source["users"].unique()))
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(CHARTS / fname)
    plt.close(fig)
    print(f"  gráfico -> results/charts/{fname}")


def make_plots(agg, operacoes, cpu_agg):
    plt.rcParams.update({"figure.dpi": 150, "font.size": 9})

    plot_line(agg, "avg_ms", "avg_ms_std", "Tempo médio de resposta (ms)",
              "Tempo médio x número de usuários", "tempo_medio_vs_usuarios.png")
    plot_line(agg, "p95_ms", "p95_ms_std", "P95 de resposta (ms)",
              "P95 x número de usuários", "p95_vs_usuarios.png")
    plot_line(agg, "rps", "rps_std", "Vazão (req/s)",
              "Vazão x número de usuários", "vazao_vs_usuarios.png")
    plot_line(agg, "fail_pct", "fail_pct_std", "Taxa de falhas (%)",
              "Taxa de falhas x número de usuários", "falhas_vs_usuarios.png")

    if not operacoes.empty:
        op = (operacoes.groupby(["profile", "users", "operacao"])["avg_ms"]
              .agg(["mean", "std"]).reset_index())
        ops = sorted(op["operacao"].unique())
        users = sorted(op["users"].unique())
        fig, axes = plt.subplots(2, 2, figsize=(9, 6.5))
        for ax, operacao in zip(axes.flat, ops):
            for profile, color in STYLE.items():
                sub = op[(op["profile"] == profile) & (op["operacao"] == operacao)]
                sub = sub.sort_values("users")
                if sub.empty:
                    continue
                ax.errorbar(sub["users"], sub["mean"], yerr=sub["std"],
                            marker="o", capsize=3, color=color, label=LABEL[profile])
            ax.set_title(operacao)
            ax.set_xlabel("Usuários virtuais")
            ax.set_ylabel("Tempo médio (ms)")
            ax.set_xticks(users)
            ax.grid(alpha=0.3)
        axes[0][0].legend()
        fig.tight_layout()
        fig.savefig(CHARTS / "operacoes_vs_cenarios.png")
        plt.close(fig)
        print("  gráfico -> results/charts/operacoes_vs_cenarios.png")

    if not cpu_agg.empty:
        services = sorted(cpu_agg["container"].unique())
        users = sorted(cpu_agg["users"].unique())
        fig, axes = plt.subplots(1, len(services),
                                 figsize=(4 * len(services), 4), squeeze=False)
        for ax, service in zip(axes[0], services):
            for profile, color in STYLE.items():
                sub = cpu_agg[(cpu_agg["profile"] == profile) &
                              (cpu_agg["container"] == service)].sort_values("users")
                if sub.empty:
                    continue
                ax.errorbar(sub["users"], sub["cpu_percent"], yerr=sub["cpu_std"],
                            marker="o", capsize=3, color=color, label=LABEL[profile])
            ax.set_title(service)
            ax.set_xlabel("Usuários virtuais")
            ax.set_ylabel("CPU média (%)")
            ax.set_xticks(users)
            ax.grid(alpha=0.3)
        axes[0][0].legend()
        fig.tight_layout()
        fig.savefig(CHARTS / "cpu_vs_usuarios.png")
        plt.close(fig)
        print("  gráfico -> results/charts/cpu_vs_usuarios.png")


def describe(profile, users):
    return f"{LABEL[profile]} | {SCENARIO_LABEL.get(users, str(users) + 'u')}"


def key_numbers(agg, operacoes):
    worst_fail = agg.sort_values("fail_pct", ascending=False).iloc[0]
    best_rps_row = agg.sort_values("rps", ascending=False).iloc[0]
    worst_p95 = agg.sort_values("p95_ms", ascending=False).iloc[0]
    best_avg = agg.sort_values("avg_ms").iloc[0]

    degradacao_global = []
    for profile in ("read", "write"):
        sub = agg[agg["profile"] == profile].sort_values("users")
        if len(sub) >= 2:
            d = (sub.iloc[-1]["avg_ms"] / sub.iloc[0]["avg_ms"] - 1.0) * 100.0
            degradacao_global.append(
                f"- {LABEL[profile]}: tempo médio {sub.iloc[0]['avg_ms']:.1f} ms (30u) -> "
                f"{sub.iloc[-1]['avg_ms']:.1f} ms ({int(sub.iloc[-1]['users'])}u) = "
                f"{d:+.0f}%"
            )

    degradacao_ops = []
    if not operacoes.empty:
        umax = int(operacoes["users"].max())
        umin = int(operacoes["users"].min())
        for operacao in sorted(operacoes["operacao"].dropna().unique()):
            low = operacoes[(operacoes["operacao"] == operacao) & (operacoes["users"] == umin)]
            high = operacoes[(operacoes["operacao"] == operacao) & (operacoes["users"] == umax)]
            if high.empty or low.empty:
                continue
            d = high["avg_ms"].mean() - low["avg_ms"].mean()
            degradacao_ops.append(f"- {operacao}: média {low['avg_ms'].mean():.1f} ms ({umin}u) -> "
                                  f"{high['avg_ms'].mean():.1f} ms ({umax}u) = {d:+.1f} ms")

    linhas = [
        "# Números-chave para a análise do README",
        "",
        "> Gerado automaticamente por scripts/analyze.py. Copie estes números",
        "> para a seção de análise do README.md, junto com os gráficos de results/charts/.",
        "",
        "## 1) Como o aumento de usuários afeta o tempo de resposta?",
        f"- Tempo médio mais baixo: {describe(best_avg['profile'], int(best_avg['users']))} => {best_avg['avg_ms']:.1f} ms",
        f"- P95 mais alto:          {describe(worst_p95['profile'], int(worst_p95['users']))} => {worst_p95['p95_ms']:.1f} ms",
        "",
        "Degradando 30u -> cenário mais pesado:",
        *degradacao_global,
        "",
        "Degradação por operação (média entre repetições):",
        *degradacao_ops,
        "",
        "## 2) Qual perfil apresenta maior vazão?",
        f"- Maior vazão: {describe(best_rps_row['profile'], int(best_rps_row['users']))} => {best_rps_row['rps']:.1f} req/s",
    ]

    for profile in ("read", "write"):
        sub = agg[agg["profile"] == profile]
        if not sub.empty:
            mx = sub.sort_values("rps", ascending=False).iloc[0]
            linhas.append(f"- {LABEL[profile]}, melhor config: {describe(profile, int(mx['users']))} => {mx['rps']:.1f} req/s")

    linhas += [
        "",
        "## 3) Quais operações apresentam maior degradação?",
        "- Veja results/tables/operacoes.md e results/charts/operacoes_vs_cenarios.png.",
        "",
        "## 4) Como o consumo de CPU varia entre os cenários?",
        "- Veja results/tables/cpu_servicos.md e results/charts/cpu_vs_usuarios.png.",
        "",
        "## 5) Qual cenário apresenta maior taxa de falhas?",
        f"- Maior taxa: {describe(worst_fail['profile'], int(worst_fail['users']))} => {worst_fail['fail_pct']:.2f}% de falhas",
        "",
    ]

    path = TABLES / "numeros_chave.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    print("  tabela -> results/tables/numeros_chave.md")


def main() -> int:
    TABLES.mkdir(parents=True, exist_ok=True)
    CHARTS.mkdir(parents=True, exist_ok=True)

    resumo, operacoes, cpu = load_all_runs()
    if resumo is None or resumo.empty:
        print("Nenhum resultado de medição em results/raw/")
        print("Rode scripts/run_experiments.sh antes deste script.")
        return 1

    print()
    print("Execuções (MEDIÇÃO; aquecimento descartado) por configuração:")
    print(resumo.groupby(["profile", "users"])["rep"].nunique().to_string())

    # média e desvio padrão entre repetições
    agg = (resumo.groupby(["profile", "users"])[METRICS]
           .agg(["mean", "std"]).reset_index())
    agg.columns = [
        f"{a}_std" if b == "std" else a
        for a, b in zip(agg.columns.get_level_values(0), agg.columns.get_level_values(1))
    ]

    print()
    print("Gerando tabelas ...")
    resumo_tabela = agg.copy().sort_values(["profile", "users"]).reset_index(drop=True)
    resumo_tabela["Perfil"] = resumo_tabela["profile"].map(PROFILE_LABEL)
    resumo_tabela["Cenario"] = resumo_tabela["users"].map(
        SCENARIO_LABEL).fillna(resumo_tabela["users"].astype(str) + "u")
    resumo_tabela = resumo_tabela.rename(columns={
        "avg_ms": "tempo_medio_ms", "p95_ms": "p95_ms",
        "rps": "vazao_req_s", "requisicoes": "total_reqs", "fail_pct": "falha_pct",
    })
    ordem = ["Perfil", "Cenario", "tempo_medio_ms", "p95_ms", "vazao_req_s",
             "total_reqs", "falha_pct"]
    resumo_tabela = resumo_tabela[ordem]
    write_table("resumo_geral",
                "Resumo geral - media e desvio-padrao das 10 repeticoes (aquecimento descartado)",
                resumo_tabela)

    if not operacoes.empty:
        op = (operacoes.groupby(["profile", "operacao"])["avg_ms"]
              .agg(["mean", "std"]).reset_index())
        vfs = (operacoes.groupby(["profile", "operacao"])["requests"].sum() /
               (MEASURED_MINUTES * 60.0) ).rename("vazao_req_s").reset_index()
        op = op.merge(vfs, on=["profile", "operacao"], how="left")
        op["Perfil"] = op["profile"].map(PROFILE_LABEL)
        op = op.rename(columns={"operacao": "Operacao", "mean": "tempo_medio_ms", "std": "dp_ms"})
        op_out = op[["Perfil", "Operacao", "tempo_medio_ms", "dp_ms", "vazao_req_s"]]
        op_out = op_out.sort_values(["Perfil", "Operacao"]).reset_index(drop=True)
        write_table("operacoes", "Tempo médio e vazão por operação", op_out)

    if not cpu.empty:
        cpu_agg = (cpu.groupby(["profile", "users", "container"])["cpu_percent"]
                   .agg(cpu_percent="mean", cpu_std="std", cpu_max="max").reset_index())
        cpu_tbl = cpu_agg.copy()
        cpu_tbl["Perfil"] = cpu_tbl["profile"].map(PROFILE_LABEL)
        cpu_tbl["Cenario"] = cpu_tbl["users"].map(
            SCENARIO_LABEL).fillna(cpu_tbl["users"].astype(str) + "u")
        cpu_tbl = cpu_tbl.rename(columns={"container": "Servico", "cpu_percent": "cpu_media_pct",
                                          "cpu_std": "dp_pct", "cpu_max": "cpu_max_pct"})
        cpu_tbl = cpu_tbl[["Perfil", "Cenario", "Servico", "cpu_media_pct", "dp_pct", "cpu_max_pct"]]
        cpu_tbl = cpu_tbl.sort_values(["Perfil", "Servico", "Cenario"]).reset_index(drop=True)
        write_table("cpu_servicos", "Utilização de CPU por serviço (docker stats)", cpu_tbl)
    else:
        cpu_agg = pd.DataFrame()

    key_numbers(agg, operacoes)

    print()
    print("Gerando gráficos ...")
    make_plots(agg, operacoes, cpu_agg)

    print()
    print("Análise concluída -> results/tables/ e results/charts/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
