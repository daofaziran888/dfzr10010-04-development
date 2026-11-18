<template>
  <section class="page" data-module="rollback">
    <header class="page-head">
      <div>
        <h2>数据回滚恢复管理</h2>
        <p class="page-desc">读取回滚记录并预演恢复：联动表快照可达性与下游迁移状态合成恢复计划，回滚影响范围与血缘影响清单同源发布。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记回滚记录</button>
        <button class="btn" type="button" @click="exportRows">导出数据回滚恢复清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
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
          <th>预演与动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="submitRehearsal(row)">提交回滚预演</button>
            <button class="link" type="button" @click="viewRehearsal(row)">影响详情</button>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无数据回滚恢复数据，可先登记回滚记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据回滚恢复记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <RehearsalDrawer v-model:open="drawerOpen" :batch="rehearsalBatch" :loading="drawerLoading" />
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import RehearsalDrawer from './RehearsalDrawer.vue'

type Row = Record<string, string | number | null>
type RehearsalBatch = Record<string, unknown>

const ENDPOINT = '/api/rollback'
const columns = ["记录编号", "表名称", "回滚版本", "回滚原因", "影响范围", "恢复耗时", "回滚时间", "回滚状态"]
const actions = ["执行回滚", "确认恢复", "归档记录"]
const stats = [
  { label: "回滚记录总数", value: 0 },
  { label: "已生成预演批次", value: 0 },
  { label: "待回滚记录", value: 0 },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const drawerOpen = ref(false)
const drawerLoading = ref(false)
const rehearsalBatch = ref<RehearsalBatch | null>(null)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '回滚记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('数据回滚恢复动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据回滚恢复操作失败'
  }
}

/** 提交回滚预演：恢复快照、下游表、未提交迁移在同一预演批次内一次合成。 */
async function submitRehearsal(row: Row) {
  errorMessage.value = ''
  drawerLoading.value = true
  drawerOpen.value = true
  rehearsalBatch.value = null
  try {
    const response = await request(`${ENDPOINT}/${row.id}/rehearsal`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '回滚预演未生成，请稍后重试')
    }
    rehearsalBatch.value = payload.entry as RehearsalBatch
    await reload()
  } catch (error) {
    drawerOpen.value = false
    errorMessage.value = error instanceof Error ? error.message : '回滚预演提交失败'
  } finally {
    drawerLoading.value = false
  }
}

/** 打开影响详情：逐项核对恢复前表快照与受影响下游表，数据仍来自同一预演批次。 */
async function viewRehearsal(row: Row) {
  errorMessage.value = ''
  drawerLoading.value = true
  drawerOpen.value = true
  rehearsalBatch.value = null
  try {
    const response = await request(`${ENDPOINT}/${row.id}/rehearsal`)
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: '预演详情读取失败' }))
      throw new Error(payload.detail || '预演详情读取失败')
    }
    rehearsalBatch.value = (await response.json()) as RehearsalBatch
  } catch (error) {
    drawerOpen.value = false
    errorMessage.value = error instanceof Error ? error.message : '预演详情读取失败'
  } finally {
    drawerLoading.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('回滚记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats[0].value = total.value
    stats[1].value = rows.value.filter((row) => Boolean(row['预演批次号'])).length
    stats[2].value = rows.value.filter((row) => row['回滚状态'] === '待回滚').length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据回滚恢复列表读取失败'
  }
}

onMounted(reload)
</script>
