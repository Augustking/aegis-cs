<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名与密码')
    return
  }
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    router.push(route.query.next || '/agent/inbox')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <span class="brand-mark">知</span>
      <h1>坐席登录</h1>
      <p class="tip">仅商家员工可进入处理台与复盘页面</p>
      <form @submit.prevent="submit">
        <label>用户名
          <input v-model="form.username" autocomplete="username" placeholder="坐席用户名" />
        </label>
        <label>密码
          <input v-model="form.password" type="password" autocomplete="current-password" placeholder="密码" />
        </label>
        <button type="submit" class="primary" :disabled="loading">{{ loading ? '登录中…' : '登录' }}</button>
      </form>
      <p class="hint">演示环境默认账号：agent / aegis-demo（可在 .env 中修改口令）</p>
      <router-link class="back" to="/chat">返回客户咨询</router-link>
    </div>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100%; background: #f5f6f8; display: flex; align-items: center; justify-content: center; padding: 20px; }
.login-card { width: 360px; background: #fff; border: 1px solid #ebedf0; border-radius: 12px; padding: 28px; display: flex; flex-direction: column; gap: 12px; }
.brand-mark { width: 38px; height: 38px; border-radius: 9px; background: #2f5460; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 600; }
h1 { font-size: 20px; margin: 4px 0 0; }
.tip { color: #86909c; font-size: 13px; margin: 0; }
form { display: flex; flex-direction: column; gap: 10px; margin-top: 8px; }
label { font-size: 13px; color: #4e5969; display: flex; flex-direction: column; gap: 4px; }
input { border: 1px solid #d5dbe1; border-radius: 8px; padding: 8px 10px; font-size: 14px; }
input:focus { outline: 2px solid #2f546033; border-color: #2f5460; }
.primary { background: #2f5460; color: #fff; border: none; border-radius: 8px; padding: 9px; font-size: 14px; cursor: pointer; }
.primary:disabled { opacity: .6; cursor: default; }
.hint { color: #86909c; font-size: 12px; margin: 4px 0 0; }
.back { font-size: 13px; color: #2f5460; }
</style>
