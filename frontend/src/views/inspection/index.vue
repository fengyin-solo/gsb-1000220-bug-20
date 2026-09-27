<template>
  <section class="page" data-module="inspection">
    <header class="page-head">
      <div>
        <h2>巡检计划管理</h2>
        <p class="page-desc">
          维护巡检任务，排期规则（日期范围、站点每日轮次上限、缺陷数复检门槛）在单条登记、批量排期与轮次统计间保持一致。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡检任务</button>
        <button class="btn" type="button" @click="openBatch">批量排期</button>
        <button class="btn" type="button" @click="exportRows">导出巡检计划清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showForm" class="panel" @submit.prevent="submitForm">
      <h3 class="panel-title">{{ editingId ? `编辑巡检任务 #${editingId}` : '登记巡检任务' }}</h3>
      <div class="form-grid">
        <label class="filter-item">
          <span>巡检编号</span>
          <input v-model="form.巡检编号" required placeholder="如 INSP-0004" />
        </label>
        <label class="filter-item">
          <span>巡检站点</span>
          <input v-model="form.巡检站点" required placeholder="如 东区方阵" />
        </label>
        <label class="filter-item">
          <span>巡检类型</span>
          <select v-model="form.巡检类型">
            <option v-for="kind in inspectionTypes" :key="kind" :value="kind">{{ kind }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>计划日期</span>
          <input v-model="form.计划日期" type="date" required />
        </label>
        <label class="filter-item">
          <span>巡检人员</span>
          <input v-model="form.巡检人员" placeholder="选填" />
        </label>
        <label class="filter-item">
          <span>巡检路线</span>
          <input v-model="form.巡检路线" placeholder="选填" />
        </label>
        <label class="filter-item">
          <span>发现缺陷数</span>
          <input v-model="form.发现缺陷数" type="number" min="0" step="1" placeholder="0" />
        </label>
      </div>
      <div class="panel-actions">
        <button class="btn primary" type="submit">{{ editingId ? '保存修改' : '提交登记' }}</button>
        <button class="btn ghost" type="button" @click="closeForm">取消</button>
      </div>
    </form>

    <div v-if="showBatch" class="panel">
      <h3 class="panel-title">批量排期</h3>
      <p class="panel-hint">
        每行一条：巡检编号,巡检站点,计划日期,巡检类型,发现缺陷数。同一批次号重复提交不会累加任务。
      </p>
      <p class="panel-hint">
        当前批次号：<code>{{ batchId }}</code>
        <button class="link" type="button" @click="resetBatch">换一批</button>
      </p>
      <textarea v-model="batchText" class="batch-input" rows="5" />
      <div class="panel-actions">
        <button class="btn primary" type="button" @click="submitBatch">提交批次</button>
        <button class="btn ghost" type="button" @click="showBatch = false">收起</button>
      </div>
      <div v-if="batchResult" class="batch-result">
        <p :class="batchResult.ok ? '' : 'error-text'">{{ batchResult.message }}</p>
        <ul v-if="batchResult.rejected.length">
          <li v-for="item in batchResult.rejected" :key="item.index" class="error-text">
            第 {{ item.index + 1 }} 行（{{ item.values.巡检编号 || '未填编号' }}）：{{ item.reasons.join('；') }}
          </li>
        </ul>
      </div>
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
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEdit(row)">编辑</button>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无巡检计划数据，可先登记巡检任务</td>
        </tr>
      </tbody>
    </table>

    <section v-if="siteRounds.length" class="panel rounds-panel">
      <h3 class="panel-title">站点当日轮次</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>巡检站点</th>
            <th>计划日期</th>
            <th>已排轮次</th>
            <th>最高缺陷数</th>
            <th>任务编号</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="bucket in siteRounds" :key="`${bucket.巡检站点}-${bucket.计划日期}`">
            <td>{{ bucket.巡检站点 }}</td>
            <td>{{ bucket.计划日期 }}</td>
            <td>{{ bucket.计划轮次 }}</td>
            <td>{{ bucket.最高缺陷数 }}</td>
            <td>{{ bucket.任务编号.join('、') }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条巡检计划记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

interface SiteRound {
  巡检站点: string
  计划日期: string
  计划轮次: number
  最高缺陷数: number
  任务编号: string[]
}

interface Stats {
  总任务数: number
  状态统计: Record<string, number>
  需复检任务: number
  站点轮次: SiteRound[]
}

interface BatchResult {
  ok: boolean
  message: string
  duplicated: boolean
  created: Row[]
  rejected: { index: number; values: Row; reasons: string[] }[]
}

const ENDPOINT = '/api/inspection'
const columns = ["巡检编号", "巡检站点", "巡检类型", "计划日期", "计划轮次", "巡检人员", "巡检路线", "发现缺陷数", "巡检状态"]
const actions = ["开始巡检", "完成巡检", "标记漏检"]
const inspectionTypes = ["日常巡检", "专项巡检", "无人机巡检", "缺陷复检"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stats = ref<Stats>({ 总任务数: 0, 状态统计: {}, 需复检任务: 0, 站点轮次: [] })
const statCards = computed(() => [
  { label: '待巡检任务', value: stats.value.状态统计['待执行'] ?? 0 },
  { label: '已完成巡检', value: stats.value.状态统计['已完成'] ?? 0 },
  { label: '漏检任务', value: stats.value.状态统计['已漏检'] ?? 0 },
  { label: '需复检任务', value: stats.value.需复检任务 },
])
const siteRounds = computed(() => stats.value.站点轮次)

const emptyForm = () => ({
  巡检编号: '',
  巡检站点: '',
  巡检类型: inspectionTypes[0],
  计划日期: '',
  巡检人员: '',
  巡检路线: '',
  发现缺陷数: '0',
})
const showForm = ref(false)
const editingId = ref<number | null>(null)
const form = reactive(emptyForm())

const showBatch = ref(false)
const batchId = ref('')
const batchText = ref('')
const batchResult = ref<BatchResult | null>(null)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  Object.assign(form, emptyForm())
  editingId.value = null
  showForm.value = true
  errorMessage.value = ''
}

function openEdit(row: Row) {
  Object.assign(form, {
    巡检编号: String(row.巡检编号 ?? ''),
    巡检站点: String(row.巡检站点 ?? ''),
    巡检类型: String(row.巡检类型 ?? inspectionTypes[0]),
    计划日期: String(row.计划日期 ?? ''),
    巡检人员: String(row.巡检人员 ?? ''),
    巡检路线: String(row.巡检路线 ?? ''),
    发现缺陷数: String(row.发现缺陷数 ?? '0'),
  })
  editingId.value = Number(row.id)
  showForm.value = true
  errorMessage.value = ''
}

function closeForm() {
  showForm.value = false
  editingId.value = null
}

async function submitForm() {
  errorMessage.value = ''
  const values = { ...form, 发现缺陷数: form.发现缺陷数 === '' ? 0 : Number(form.发现缺陷数) }
  const isEdit = editingId.value !== null
  const url = isEdit ? `${ENDPOINT}/${editingId.value}` : ENDPOINT
  try {
    const response = await request(url, {
      method: isEdit ? 'PUT' : 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '排期判定未通过')
    }
    closeForm()
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检任务保存失败'
  }
}

function newBatchId() {
  return `BATCH-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function openBatch() {
  resetBatch()
  showBatch.value = true
  errorMessage.value = ''
}

function resetBatch() {
  batchId.value = newBatchId()
  batchResult.value = null
  batchText.value = [
    'INSP-B01,北区方阵,2026-09-29,日常巡检,0',
    'INSP-B02,北区方阵,2026-09-29,专项巡检,0',
  ].join('\n')
}

async function submitBatch() {
  errorMessage.value = ''
  const plans = batchText.value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [巡检编号, 巡检站点, 计划日期, 巡检类型, 发现缺陷数] = line.split(/[,，]/).map((cell) => cell.trim())
      return { 巡检编号, 巡检站点, 计划日期, 巡检类型, 发现缺陷数: 发现缺陷数 === '' || 发现缺陷数 === undefined ? 0 : Number(发现缺陷数) }
    })
  if (!plans.length) {
    errorMessage.value = '请先按格式填写要排期的计划'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({ batch_id: batchId.value, plans }),
    })
    batchResult.value = await response.json()
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量排期提交失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '巡检计划动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检计划操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('巡检任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检计划列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      stats.value = await response.json()
    }
  } catch {
    // 统计卡片读取失败不阻塞列表，下次操作时会重新拉取。
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>

<style scoped>
.panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
}
.panel-title {
  margin: 0 0 8px;
  font-size: 14px;
}
.panel-hint {
  margin: 4px 0;
  color: var(--muted);
  font-size: 12px;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}
.panel-actions {
  display: flex;
  gap: 8px;
}
.batch-input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  font-family: inherit;
  font-size: 13px;
  margin-bottom: 8px;
}
.batch-result {
  margin-top: 8px;
  font-size: 13px;
}
.rounds-panel {
  margin-top: 12px;
}
</style>
