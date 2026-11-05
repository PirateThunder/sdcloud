import { expect, type Page, test } from '@playwright/test'

async function login(page: Page, email: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByRole('button', { name: 'Получить код' }).click()
  await expect(page.getByLabel('Код из письма')).toBeVisible()
  await page.getByRole('button', { name: 'Войти в sdCloud' }).click()
  await expect(page).toHaveURL(/\/chat$/)
}

test('OTP → chat → model → graphs → simulation → exports → reload', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await login(page, `studio-${Date.now()}@example.com`)
  await page.getByLabel('Описание системы').fill('Predator prey model with rabbits and foxes.')
  await page.getByRole('button', { name: 'Отправить описание' }).click()
  const openModel = page.getByRole('link', { name: 'Открыть модель' })
  await expect(openModel).toBeVisible({ timeout: 180_000 })
  const chatUrl = page.url()
  await openModel.click()
  await expect(page).toHaveURL(/\/model-versions\//)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

  await page.getByRole('tab', { name: 'CLD', exact: true }).click()
  await expect(page.locator('.react-flow__node').first()).toBeVisible()
  expect(await page.locator('.react-flow__node').count()).toBeGreaterThan(0)
  await page.getByRole('tab', { name: 'SFD', exact: true }).click()
  await expect(page.locator('.react-flow__node').first()).toBeVisible()
  await page.getByRole('tab', { name: 'Уравнения' }).click()
  await expect(page.locator('.katex').first()).toBeVisible()
  expect(await page.locator('.katex').count()).toBeGreaterThan(0)
  await page.getByRole('tab', { name: 'Переменные' }).click()
  await expect(page.locator('.katex').first()).toBeVisible()
  expect(await page.locator('.katex').count()).toBeGreaterThan(0)

  await page.getByRole('tab', { name: 'Симуляция' }).click()
  await page.getByLabel('Конечное время').fill('1')
  await page.getByLabel('Time step').fill('0.25')
  await page.getByLabel('Saveper').fill('0.25')
  await page.getByRole('button', { name: 'Запустить симуляцию' }).click()
  await expect(page.getByLabel('Переменная')).toBeVisible({ timeout: 180_000 })
  await expect(page.locator('.recharts-line-curve')).toBeVisible()
  const csvEvent = page.waitForEvent('download')
  await page.getByRole('button', { name: 'CSV' }).click()
  expect((await csvEvent).suggestedFilename()).toBe('simulation.csv')

  await page.getByRole('tab', { name: 'Код', exact: true }).click()
  await expect(page.locator('pre')).toContainText('def')
  const pythonEvent = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Скачать Python' }).click()
  expect((await pythonEvent).suggestedFilename()).toBe('model.py')

  await page.reload()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

  await page.goto(chatUrl)
  await page.getByLabel('Описание системы').fill('What is the prey growth rate?')
  await page.getByRole('button', { name: 'Отправить описание' }).click()
  await expect(page.locator('.markdown-body')).toHaveCount(2, { timeout: 180_000 })
  await expect(page.locator('.markdown-body').last()).toContainText(/\S/)
  await expect(page.getByRole('link', { name: 'Открыть модель' })).toHaveCount(1)
  await expect(page.getByPlaceholder(/Задайте вопрос о модели/)).toBeVisible()
  const isFixture = (await page.getByText('Демо: fixture', { exact: true }).count()) > 0

  await page.getByLabel('Описание системы').fill('Set prey growth to 0.2')
  await page.getByRole('button', { name: 'Отправить описание' }).click()
  await expect(page.getByRole('link', { name: 'Открыть модель' })).toHaveCount(2, {
    timeout: 180_000,
  })
  await page.getByRole('link', { name: 'Открыть модель' }).last().click()
  await page.getByRole('tab', { name: 'Переменные' }).click()
  if (!isFixture) {
    await expect(page.locator('.katex').filter({ hasText: '0.2' }).first()).toBeVisible()
  }
  expect(errors).toEqual([])
})

test('mobile login and navigation do not overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page, `mobile-${Date.now()}@example.com`)
  await page.getByRole('button', { name: 'Открыть меню' }).click()
  await expect(page.getByRole('link', { name: 'Новая модель' })).toBeVisible()
  await page.getByRole('button', { name: 'Закрыть меню' }).last().click()
  await expect(page.getByLabel('Описание системы')).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  )
  expect(overflow).toBe(false)
})
