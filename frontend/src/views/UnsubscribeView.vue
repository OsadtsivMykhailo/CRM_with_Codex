<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const message = ref('Опрацьовуємо запит…')
const error = ref('')

onMounted(async () => {
  try { message.value = (await api(`/email-unsubscribe/${route.params.token}/`, { method: 'POST' })).detail }
  catch (e) { error.value = e.message; message.value = '' }
})
</script>

<template>
  <section class="auth-page single">
    <article class="form-card wide unsubscribe-card">
      <p class="eyebrow">EMAIL НАЛАШТУВАННЯ</p>
      <h2>Відмова від рекламних розсилок</h2>
      <p v-if="message" class="success">{{ message }}</p>
      <p v-if="error" class="error">{{ error }}</p>
      <RouterLink to="/login">Перейти до CRM</RouterLink>
    </article>
  </section>
</template>
