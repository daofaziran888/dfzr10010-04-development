<template>
  <section class="page" data-module="lineage">
    <header class="page-head">
      <div>
        <h2>湖仓血缘追踪管理</h2>
        <p class="page-desc">维护湖仓血缘的上游下游追溯、字段映射与批次记录；回滚预演发布的影响范围在本页核对，版本结论与回滚列表入口保持一致。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记血缘记录</button>
        <button class="btn" type="button" @click="exportRows">导出湖仓血缘追踪清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="drawer-section">
      <h4>血缘影响清单（回滚预演发布）</h4>
      <form class="filter-bar" @submit.prevent="loadImpacts">
        <label class="filter-item">
          <span>按表名或回滚记录编号检索</span>
          <input v-model="impactKeyword" placeholder="如 finance_ledger / ROLL-20261118-01" />
        </label>
        <button class="btn" type="submit">核对影响范围</button>
        <button class="btn ghost" type="button" @click="resetImpactFilter">重置条件</button>
        <span class="sub" style="color: var(--muted); font-size: 12px">
          与回滚列表的影响详情读取同一份预演批次数据
        </span>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in impactColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in impactRows" :key="`${String(row['预演批次号'])}-${String(row['下游表名'])}`">
            <td v-for="column in impactColumns" :key="column">
              <span v-if="column === '恢复结论'" :class="['tag', row[column] === '可恢复' ? 'ok' : 'warn']">
                {{ row[column] ?? '—' }}
              </span>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
          </tr>
          <tr v-if="!impactRows.length">
            <td :colspan="impactColumns.length" class="empty-state">
              暂无回滚影响范围，请先在「数据回滚恢复」页面提交回滚预演
            </td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ impactTotal }} 条血缘影响记录</span>
        <span v-if="impactError" class="error-text">{{ impactError }}</span>
      </footer>
    </div>

    <form class="filter-bar" @submit.prevent="reload" style="margin-top: 18px">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无湖仓血缘追踪数据，可先登记血缘记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条湖仓血缘追踪记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/lineage'
const columns = ["记录编号", "上游表名", "下游表名", "转换类型", "字段映射", "操作时间", "操作批次", "记录状态"]
const actions = ["关联血缘", "标记过期", "清理记录"]
const stats = [{"label": "血缘记录总数", "value": 0}, {"label": "已关联记录", "value": 0}, {"label": "已过期记录", "value": 0}]

const impactColumns = [
  "预演批次号",
  "回滚记录编号",
  "上游表名",
  "回滚版本",
  "下游表名",
  "恢复结论",
  "预演采用版本",
  "操作批次",
  "关联迁移批次",
  "待处理说明",
  "版本结论",
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const impactRows = ref<Row[]>([])
const impactTotal = ref(0)
const impactError = ref('')
const impactKeyword = ref('')

function resetFilters() {
  filters.value = {}
  void reload()
}

function resetImpactFilter() {
  impactKeyword.value = ''
  void loadImpacts()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '血缘记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('湖仓血缘追踪动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '湖仓血缘追踪操作失败'
  }
}

async function loadImpacts() {
  impactError.value = ''
  const query = new URLSearchParams()
  if (impactKeyword.value) {
    query.set('keyword', impactKeyword.value)
  }
  try {
    const response = await request(`${ENDPOINT}/impacts?${query.toString()}`)
    if (!response.ok) {
      throw new Error('血缘影响清单读取失败')
    }
    const payload = await response.json()
    impactRows.value = payload.items ?? []
    impactTotal.value = payload.total ?? impactRows.value.length
  } catch (error) {
    impactError.value = error instanceof Error ? error.message : '血缘影响清单读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('血缘记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '湖仓血缘追踪列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadImpacts()
})
</script>
