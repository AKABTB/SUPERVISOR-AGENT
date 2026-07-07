<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { api, fmtTime } from './api.js'

const loading = ref(true)
const error = ref('')
const data = ref(null)          // overview 响应
const banner = ref('')          // 操作提示

// 弹窗状态：mode = 'create' | 'title' | 'cadence' | ''
const modal = reactive({ open: false, mode: '', goalId: null, title: '', cadence: '' })

const primary = computed(() => data.value?.primary || null)
const queue = computed(() => data.value?.queue || [])
const logs = computed(() => data.value?.logs || [])
const stats = computed(() => data.value?.stats || { active: 0, nagged_today: 0, delivered_this_week: 0 })

async function load() {
  try {
    error.value = ''
    data.value = await api.overview()
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// 统一：执行一个写操作 → 刷新 → 捕获错误
async function act(fn, okMsg) {
  try {
    error.value = ''
    const r = await fn()
    await load()
    if (okMsg) banner.value = okMsg
    return r
  } catch (e) {
    error.value = e.message || '操作失败'
  }
}

// ---- 弹窗 ----
function openCreate() {
  Object.assign(modal, { open: true, mode: 'create', goalId: null, title: '', cadence: '' })
}
function openTitle(goal) {
  Object.assign(modal, { open: true, mode: 'title', goalId: goal.id, title: goal.title, cadence: '' })
}
function openCadence(goal) {
  Object.assign(modal, { open: true, mode: 'cadence', goalId: goal.id, title: '', cadence: goal.cadence })
}
function closeModal() { modal.open = false; modal.mode = '' }

async function submitModal() {
  if (modal.mode === 'create') {
    if (!modal.title.trim()) { error.value = '目标不能为空'; return }
    await act(() => api.createGoal(modal.title.trim(), modal.cadence.trim()))
  } else if (modal.mode === 'title') {
    if (!modal.title.trim()) { error.value = '标题不能为空'; return }
    await act(() => api.patchGoal(modal.goalId, { title: modal.title.trim() }))
  } else if (modal.mode === 'cadence') {
    await act(() => api.patchGoal(modal.goalId, { cadence: modal.cadence.trim() }))
  }
  closeModal()
}

// ---- 目标操作 ----
const setPrimary = (id) => act(() => api.setPrimary(id))
const markDone = (id) => act(() => api.markDone(id))
const archive = (id) => act(() => api.archive(id))

const modalTitle = computed(() => ({
  create: '新建目标',
  title: '改目标定义',
  cadence: '改催收频率',
}[modal.mode] || ''))

function verdictClass(v) {
  return { pass: 'pass', need_fix: 'fix', submitted: 'yes', not_submitted: 'no' }[v] || ''
}
function verdictLabel(v) {
  return { pass: 'pass', need_fix: 'need_fix', submitted: '交了', not_submitted: '没交' }[v] || v || ''
}

onMounted(load)
</script>

<template>
  <div class="wrap">
    <!-- header -->
    <div class="hd">
      <div>
        <h1>SUPERVISOR // 监督助手</h1>
        <div class="tag">// 配置面板 = 清醒的管理者。这里给全貌、可调度。手机上被催时想改？不认——回这里改。</div>
      </div>
      <div class="st" v-if="data">
        bot: <b :class="data.bot_online ? 'blink' : 'offline'">● {{ data.bot_online ? 'configured' : 'no token' }}</b><br>
        active: <b>{{ stats.active }}</b> · nagged today: <b>{{ stats.nagged_today }}</b> · delivered/7d: <b>{{ stats.delivered_this_week }}</b>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error && !data" class="banner err">{{ error }}</div>

    <template v-else>
      <!-- 错误 / 提示 banner -->
      <div class="banner" v-if="banner">
        <span class="x" @click="banner = ''">✕</span>{{ banner }}
      </div>
      <div class="banner err" v-if="error">
        <span class="x" @click="error = ''">✕</span>{{ error }}
      </div>

      <!-- 主攻 -->
      <div class="sec"><span>&gt; PRIMARY_TARGET</span><span>只催它 · 其他排队</span></div>
      <div class="primary" v-if="primary">
        <span class="lbl">当下主攻 #{{ primary.goal.id }}</span>
        <div class="title">{{ primary.goal.title }}</div>
        <div class="meta">
          <span>cadence=<b>{{ primary.goal.cadence_desc }}</b></span>
          <span>nagged=<b>{{ primary.nagged }}</b></span>
          <span>delivered=<b>{{ primary.delivered }}</b></span>
          <span v-if="primary.last_verdict">last=<b :style="{ color: primary.last_verdict === 'pass' ? 'var(--green)' : 'var(--red)' }">{{ primary.last_verdict }}</b></span>
        </div>
        <div class="acts">
          <button class="b" @click="openTitle(primary.goal)">改目标定义</button>
          <button class="b" @click="openCadence(primary.goal)">改频率</button>
          <button class="b" @click="markDone(primary.goal.id)">标记交掉 ✓</button>
        </div>
      </div>
      <div class="empty" v-else>
        没有当下主攻。新建一个目标，或把队列里的某个设为主攻——只有主攻会被催。
      </div>

      <!-- 队列 -->
      <div class="sec">
        <span>&gt; GOAL_QUEUE</span>
        <button class="b sm" @click="openCreate">+ 新目标</button>
      </div>
      <div v-if="queue.length">
        <div class="g" v-for="g in queue" :key="g.id">
          <span class="id">#{{ g.id }}</span>
          <span class="t">{{ g.title }}</span>
          <span class="badge q">排队</span>
          <span class="cad">{{ g.cadence_desc }}</span>
          <span class="rowacts">
            <button class="b sm" @click="setPrimary(g.id)">设主攻</button>
            <button class="b sm" @click="markDone(g.id)">交掉</button>
            <button class="b sm" @click="archive(g.id)">归档</button>
          </span>
        </div>
      </div>
      <div class="empty" v-else>队列空。{{ primary ? '其他目标都在主攻位或已结掉。' : '' }}</div>

      <!-- 日志 -->
      <div class="sec"><span>&gt; LOG // 催收 · 审查</span><span>近 {{ logs.length }} 条</span></div>
      <div v-if="logs.length">
        <div class="l" v-for="(it, i) in logs" :key="i">
          <span class="tm">{{ fmtTime(it.at) }}</span>
          <span class="vd" :class="verdictClass(it.verdict)">{{ verdictLabel(it.verdict) }}</span>
          <span class="tx">#{{ it.goal_id }} {{ it.text }}</span>
        </div>
      </div>
      <div class="empty" v-else>还没有催收或交货记录。</div>

      <div class="foot">
        <span class="prompt">$</span> 风格 C · 极简终端 — 只认交没交。这里能改，手机上被催时不许改。
      </div>
    </template>

    <!-- 弹窗 -->
    <div class="mask" v-if="modal.open" @click.self="closeModal">
      <div class="modal">
        <h3>{{ modalTitle }}</h3>
        <div class="field" v-if="modal.mode === 'create' || modal.mode === 'title'">
          <label>目标（要小到今天就能出体）</label>
          <input v-model="modal.title" @keyup.enter="submitModal" placeholder="例：写完登录页" autofocus>
        </div>
        <div class="field" v-if="modal.mode === 'create' || modal.mode === 'cadence'">
          <label>催收频率</label>
          <input v-model="modal.cadence" @keyup.enter="submitModal" placeholder="每天20:00 / 每2小时 / 每30分钟">
          <div class="hint">留空 = 每天20:00。只对主攻目标催收。</div>
        </div>
        <div class="acts">
          <button class="b" @click="closeModal">取消</button>
          <button class="b danger" @click="submitModal">确定</button>
        </div>
      </div>
    </div>
  </div>
</template>
