<template>
  <section class="page" data-module="inspection">
    <header class="page-head">
      <div>
        <h2>巡检计划管理</h2>
        <p class="page-desc">维护巡检任务，围绕巡检编号、巡检站点、巡检类型、计划日期做登记、批量排期、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡检任务</button>
        <button class="btn" type="button" @click="openBatch">批量排期</button>
        <button class="btn" type="button" @click="exportRows">导出巡检计划清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">今日已排轮次</span>
        <strong class="stat-value">{{ todayRounds }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model="filters[field.key]" :placeholder="`按${field.label}检索`" />
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

    <footer class="page-foot">
      <span>共 {{ total }} 条巡检计划记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="editing" class="modal-mask" @click.self="closeForm">
      <form class="modal" @submit.prevent="submitForm">
        <h3>{{ editing.id ? '编辑巡检任务' : '登记巡检任务' }}</h3>
        <label v-for="field in formFields" :key="field" class="form-item">
          <span>{{ field }}</span>
          <input
            v-model="form[field]"
            :type="field === '计划日期' ? 'date' : field === '发现缺陷数' ? 'number' : 'text'"
            :min="field === '发现缺陷数' ? 0 : undefined"
          />
        </label>
        <p class="form-hint">排期规则：计划日期在今天起 30 天内；同一站点同一天最多 2 轮；发现缺陷数达到 5 需先转故障处置。</p>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit">保存</button>
          <button class="btn ghost" type="button" @click="closeForm">取消</button>
        </div>
      </form>
    </div>

    <div v-if="batchOpen" class="modal-mask" @click.self="batchOpen = false">
      <div class="modal">
        <h3>批量排期</h3>
        <p class="form-hint">每行一条计划，逗号分隔：巡检编号,巡检站点,巡检类型,计划日期,巡检人员,巡检路线,发现缺陷数</p>
        <textarea v-model="batchText" rows="8" placeholder="INSP-0101,1号方阵,日常巡检,2026-10-08,张伟,东线,0"></textarea>
        <p v-if="batchMessage" class="form-hint">{{ batchMessage }}</p>
        <ul v-if="batchRejections.length" class="rejection-list">
          <li v-for="(item, index) in batchRejections" :key="index">{{ item }}</li>
        </ul>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="submitBatch">提交排期</button>
          <button class="btn ghost" type="button" @click="batchOpen = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/inspection'
const columns = ["巡检编号", "巡检站点", "巡检类型", "计划日期", "计划轮次", "巡检人员", "巡检路线", "发现缺陷数", "巡检状态"]
const actions = ["开始巡检", "完成巡检", "标记漏检"]
const formFields = ["巡检编号", "巡检站点", "巡检类型", "计划日期", "巡检人员", "巡检路线", "发现缺陷数"]
const filterFields = [
  { key: 'keyword', label: '巡检编号' },
  { key: 'site', label: '巡检站点' },
  { key: 'inspect_type', label: '巡检类型' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([{ label: '待巡检任务', value: 0 }, { label: '已完成巡检', value: 0 }, { label: '漏检任务', value: 0 }])
const todayRounds = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})

const editing = ref<Row | null>(null)
const form = ref<Record<string, string>>({})
const formError = ref('')

const batchOpen = ref(false)
const batchText = ref('')
const batchMessage = ref('')
const batchRejections = ref<string[]>([])

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  editing.value = {}
  form.value = {}
  formError.value = ''
}

function openEdit(row: Row) {
  editing.value = row
  form.value = Object.fromEntries(formFields.map((field) => [field, String(row[field] ?? '')]))
  formError.value = ''
}

function closeForm() {
  editing.value = null
}

async function submitForm() {
  formError.value = ''
  const id = editing.value?.id
  const url = id ? `${ENDPOINT}/${id}` : ENDPOINT
  try {
    const response = await request(url, {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify({ values: form.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '巡检任务保存失败')
    }
    closeForm()
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '巡检任务保存失败'
  }
}

function openBatch() {
  batchOpen.value = true
  batchText.value = ''
  batchMessage.value = ''
  batchRejections.value = []
}

async function submitBatch() {
  batchMessage.value = ''
  batchRejections.value = []
  const items = batchText.value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const cells = line.split(/[,，]/).map((cell) => cell.trim())
      return Object.fromEntries(formFields.map((field, index) => [field, cells[index] ?? '']))
    })
  if (!items.length) {
    batchMessage.value = '请先粘贴要排期的计划行'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '批量排期提交失败')
    }
    const { created, skipped, rejected } = payload.summary
    batchMessage.value = `排期完成：新增 ${created} 条，跳过重复 ${skipped} 条，拦截 ${rejected} 条`
    batchRejections.value = (payload.rejected ?? []).map(
      (item: { values: Record<string, string>; reasons: string[] }) =>
        `${item.values['巡检编号'] || '未填编号'}：${item.reasons.join('；')}`,
    )
    await reload()
  } catch (error) {
    batchMessage.value = error instanceof Error ? error.message : '批量排期提交失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '巡检计划动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检计划操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value)),
  ).toString()
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResponse.ok) {
      throw new Error('巡检任务列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (statsResponse.ok) {
      const statsPayload = await statsResponse.json()
      stats.value = statsPayload.cards ?? stats.value
      todayRounds.value = statsPayload.today_rounds ?? 0
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检计划列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}

.modal {
  background: #fff;
  border-radius: 10px;
  padding: 20px;
  width: 420px;
  max-width: 92vw;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.form-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.form-item span {
  width: 80px;
  flex-shrink: 0;
}

.form-item input {
  flex: 1;
}

.modal textarea {
  width: 100%;
  box-sizing: border-box;
}

.form-hint {
  color: #6b7280;
  font-size: 12px;
  margin: 0;
}

.modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.rejection-list {
  margin: 0;
  padding-left: 18px;
  color: #b91c1c;
  font-size: 12px;
  max-height: 140px;
  overflow: auto;
}
</style>
