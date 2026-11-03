import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ChatComposer } from '@/fsd/features/chat-send/chat-composer'

describe('ChatComposer', () => {
  it('submits on Enter and keeps Shift+Enter as a newline', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    function Wrapper() {
      const [value, setValue] = useState('')
      return <ChatComposer value={value} onChange={setValue} onSubmit={onSubmit} pending={false} />
    }
    render(<Wrapper />)
    const input = screen.getByLabelText('Описание системы')
    await user.type(input, 'System description')
    await user.keyboard('{Shift>}{Enter}{/Shift}')
    expect(onSubmit).not.toHaveBeenCalled()
    await user.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledOnce()
  })

  it('offers questions and edits in an existing conversation', () => {
    render(
      <ChatComposer value="" onChange={() => {}} onSubmit={() => {}} pending={false} contextual />,
    )
    expect(
      screen.getByPlaceholderText('Задайте вопрос о модели или опишите нужное изменение…'),
    ).toBeVisible()
  })

  it('blocks an empty submit', async () => {
    const user = userEvent.setup()
    render(<ChatComposer value=" " onChange={() => {}} onSubmit={() => {}} pending={false} />)
    expect(screen.getByRole('button', { name: 'Отправить описание' })).toBeDisabled()
    await user.keyboard('{Enter}')
  })
})
