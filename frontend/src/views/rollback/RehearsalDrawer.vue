<template>
  <template v-if="open">
    <div class="drawer-mask" @click="close" />
    <aside class="drawer" role="dialog" aria-label="回滚恢复预演详情">
      <div class="drawer-head">
        <div>
          <h3>回滚恢复预演详情</h3>
          <div class="sub">
            <template v-if="batch">
              预演批次 {{ String(batch['预演批次号']) }} · 回滚单 {{ String(batch['回滚记录编号']) }}
              · {{ String(batch['表名称']) }} 回滚至 {{ String(batch['回滚版本']) }} · {{ String(batch['预演时间']) }}
            </template>
            <template v-else>正在合成恢复计划…</template>
          </div>
        </div>
        <button class="btn ghost" type="button" @click="close">关闭</button>
      </div>

      <div v-if="loading" class="empty-state">正在读取回滚记录、表快照与迁移状态，请稍候…</div>

      <template v-else-if="batch">
        <section class="drawer-section">
          <h4>版本结论与影响范围</h4>
          <p class="scope-note">{{ String(batch['版本结论']) }}</p>
          <p class="scope-note" style="margin-top: 6px">
            影响范围表清单：{{ scopeTables.join('、') }}<br />
            影响摘要：{{ String(batch['影响范围摘要']) }}
          </p>
        </section>

        <section class="drawer-section">
          <h4>快照可达性核对（恢复前表快照）</h4>
          <ul class="check-list">
            <li v-for="check in snapshotChecks" :key="String(check['判定项'])">
              <span :class="['tag', check['通过'] ? 'ok' : 'warn']">
                {{ check['通过'] ? '通过' : '不通过' }}
              </span>
              {{ String(check['判定项']) }}：{{ String(check['说明']) }}
            </li>
          </ul>
          <table v-if="recoverySnapshot" class="sub-table" style="margin-top: 8px">
            <tbody>
              <tr v-for="field in snapshotFields" :key="field">
                <th style="width: 120px">{{ field }}</th>
                <td>{{ recoverySnapshot[field] ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="scope-note" style="margin-top: 8px">回滚版本未指向可恢复快照，无恢复落点。</p>
        </section>

        <section class="drawer-section">
          <h4>受影响下游表逐项核对（{{ downstreamPlans.length }} 张）</h4>
          <table class="sub-table">
            <thead>
              <tr>
                <th>下游表名</th>
                <th>恢复结论</th>
                <th>预演采用版本</th>
                <th>血缘操作批次</th>
                <th>待处理说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="plan in downstreamPlans" :key="String(plan['下游表名'])">
                <td>{{ String(plan['下游表名']) }}</td>
                <td>
                  <span :class="['tag', plan['恢复结论'] === '可恢复' ? 'ok' : 'warn']">
                    {{ String(plan['恢复结论']) }}
                  </span>
                </td>
                <td>{{ plan['预演采用版本'] ?? '—' }}</td>
                <td>{{ plan['操作批次'] ?? '—' }}</td>
                <td>{{ plan['待处理说明'] || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p class="scope-note" style="margin-top: 6px">
            已完成恢复集合：{{ recoveredTables.length ? recoveredTables.join('、') : '空' }}
            ｜ 待处理集合：{{ pendingTables.length ? pendingTables.join('、') : '空' }}
          </p>
        </section>

        <section class="drawer-section">
          <h4>未提交迁移（{{ uncommittedMigrations.length }} 项）</h4>
          <table v-if="uncommittedMigrations.length" class="sub-table">
            <thead>
              <tr>
                <th>任务编号</th>
                <th>源表名</th>
                <th>目标表名</th>
                <th>迁移状态</th>
                <th>数据范围</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="task in uncommittedMigrations" :key="String(task['任务编号'])">
                <td>{{ String(task['任务编号']) }}</td>
                <td>{{ String(task['源表名']) }}</td>
                <td>{{ String(task['目标表名']) }}</td>
                <td><span class="tag warn">{{ String(task['迁移状态']) }}</span></td>
                <td>{{ String(task['数据范围']) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="scope-note">当前预演批次没有未提交迁移，时间窗口内迁移提交后的表版本可直接进入预演。</p>
        </section>

        <section class="drawer-section">
          <h4>预演约束口径</h4>
          <div class="scope-note">
            <template v-for="(text, key) in constraintRules" :key="String(key)">
              · {{ String(text) }}<br />
            </template>
          </div>
        </section>
      </template>
    </aside>
  </template>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface SnapshotCheck {
  判定项: string
  通过: boolean
  说明: string
}

interface SnapshotInfo {
  [key: string]: string | undefined
  快照编号?: string
  表名称?: string
  快照版本?: string
  快照时间?: string
  快照状态?: string
  快照大小?: string
  保留天数?: string
  创建方式?: string
}

interface DownstreamPlan {
  下游表名: string
  血缘记录编号?: string
  转换类型?: string
  操作批次?: string
  恢复结论: string
  预演采用版本?: string | null
  恢复快照编号?: string | null
  待处理说明?: string
  未提交迁移: Array<{ 任务编号: string }>
}

interface MigrationTask {
  任务编号: string
  源表名: string
  目标表名: string
  迁移状态: string
  数据范围: string
}

const props = defineProps<{
  open: boolean
  batch: Record<string, unknown> | null
  loading: boolean
}>()

const emit = defineEmits<{ (event: 'update:open', value: boolean): void }>()

function close() {
  emit('update:open', false)
}

const snapshotChecks = computed<SnapshotCheck[]>(() =>
  (props.batch?.['快照核对'] as SnapshotCheck[] | undefined) ?? [],
)
const recoverySnapshot = computed<SnapshotInfo | null>(
  () => (props.batch?.['恢复快照'] as SnapshotInfo | null) ?? null,
)
const downstreamPlans = computed<DownstreamPlan[]>(
  () => (props.batch?.['下游表'] as DownstreamPlan[] | undefined) ?? [],
)
const uncommittedMigrations = computed<MigrationTask[]>(
  () => (props.batch?.['未提交迁移'] as MigrationTask[] | undefined) ?? [],
)
const recoveredTables = computed<string[]>(
  () => (props.batch?.['已完成恢复集合'] as string[] | undefined) ?? [],
)
const pendingTables = computed<string[]>(
  () => (props.batch?.['待处理集合'] as string[] | undefined) ?? [],
)
const scopeTables = computed<string[]>(
  () => (props.batch?.['影响范围表清单'] as string[] | undefined) ?? [],
)
const constraintRules = computed<Record<string, unknown>>(
  () => (props.batch?.['约束口径'] as Record<string, unknown> | undefined) ?? {},
)

const snapshotFields = ['快照编号', '表名称', '快照版本', '快照时间', '快照状态', '快照大小', '保留天数', '创建方式']
</script>
