<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, auth } from '../api'

const emit = defineEmits(['authenticated'])
const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const data = await api('/auth/login/', {
      method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }),
    })
    auth.set(data.token, data.user)
    emit('authenticated', data.user)
    await router.push(data.user.role === 'client' ? '/my-account' : '/')
  } catch (e) { error.value = e.message }
  finally { loading.value = false }
}
</script>

<template>
  <section class="auth-page">
    <div class="auth-panel intro">
      <p class="eyebrow">CRM ДЛЯ IT-КОМАНДИ</p>
      <h1>Клієнти, команди й доступи — в одному місці.</h1>
      <p>Робоча альфа-версія локальної CRM.</p>
    </div>
    <form class="auth-panel form-card" @submit.prevent="submit">
      <h2>Вхід до системи</h2>
      <label>Логін<input v-model="username" autocomplete="username" required /></label>
      <label>Пароль<input v-model="password" type="password" autocomplete="current-password" required /></label>
      <p v-if="error" class="error">{{ error }}</p>
      <button :disabled="loading">{{ loading ? 'Вхід…' : 'Увійти' }}</button>
      <RouterLink to="/register">Зареєструватися як клієнт</RouterLink>
    </form>
  </section>
</template>
