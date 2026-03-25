# Codebase Map
_Auto-generated: 2026-03-24 13:30 UTC_

## Directory Structure

### src/
  - **analysis/** (7 py)
  - **channels/** (9 py)
    - **telegram/** (2 py)
        (2 files)
    - **wechat/** (5 py)
        (5 files)
    - **wecom/** (2 py)
        (2 files)
  - **collectors/** (16 py)
    - **yaml/**
        (1 files)
  - **core/** (9 py)
  - **gateway/** (7 py)
  - **governance/** (9 py)
    - **audit/** (5 py)
        (5 files)
    - **budget/** (2 py)
        (2 files)
    - **condenser/** (7 py)
        (7 files)
    - **context/** (7 py)
        (7 files)
    - **events/** (2 py)
        (2 files)
    - **learning/** (10 py)
        (10 files)
    - **pipeline/** (8 py)
        (8 files)
    - **policy/** (8 py)
        (8 files)
    - **preflight/** (2 py)
        (2 files)
    - **quality/** (3 py)
        (3 files)
    - **safety/** (10 py)
        (10 files)
    - **signals/** (2 py)
        (2 files)
  - **desktop_use/** (10 py)
  - **jobs/** (6 py)
  - **storage/** (3 py)
  - **tmp/**
    - **outcomes/**
        (5 files)
  - **voice/** (3 py)

### departments/
  - **engineering/**
    - **guidelines/**
        (4 files)
  - **operations/**
    - **guidelines/**
  - **personnel/**
    - **guidelines/**
  - **protocol/**
    - **guidelines/**
  - **quality/**
    - **guidelines/**
        (1 files)
  - **security/**
    - **guidelines/**
  - **shared/**

### SOUL/
  - **examples/**
    - **orchestrator-butler/**
        (3 files)
  - **private/**
    - **prompts/**
        (6 files)
  - **public/**
    - **prompts/**
        (7 files)
  - **tools/** (4 py)

### dashboard/
  - **public/**
    - **audio/**

## Key Modules

- **src/core/** — 核心基础设施 (event_bus, llm_router, config)
- **src/governance/** — 治理管线 (executor, scrutiny, pipeline, safety, learning)
- **src/gateway/** — 前门路由 (intent, dispatcher, classifier)
- **src/storage/** — 数据存储 (events_db, vector_db)
- **src/channels/** — 通信通道 (telegram, wechat)
- **src/collectors/** — 数据采集器
- **src/analysis/** — 分析引擎 (daily_analyst, profile, performance)
- **src/jobs/** — 定时任务 (scheduler, periodic)
- **departments/** — 六部配置 (SKILL.md, manifest.yaml, guidelines/)
- **SOUL/** — 灵魂系统 (identity, voice, management, compiler)