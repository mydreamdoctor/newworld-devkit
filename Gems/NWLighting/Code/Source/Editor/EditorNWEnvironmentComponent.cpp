/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 */

#include "EditorNWEnvironmentComponent.h"

#include <AzCore/Serialization/EditContext.h>
#include <AzCore/Serialization/SerializeContext.h>

namespace NWLighting
{
    void EditorNWEnvironmentComponent::Reflect(AZ::ReflectContext* context)
    {
        // Reflect the runtime class too: the gem's runtime module and this
        // editor module can load in either order, and each Reflect is
        // guarded so only the first registration sticks.
        NWEnvironmentComponent::Reflect(context);

        if (auto* serialize = azrtti_cast<AZ::SerializeContext*>(context))
        {
            serialize->Class<EditorNWEnvironmentComponent, AzToolsFramework::Components::EditorComponentBase>()
                ->Version(1)
                ->Field("Configuration", &EditorNWEnvironmentComponent::m_config);

            if (auto* edit = serialize->GetEditContext())
            {
                edit->Class<EditorNWEnvironmentComponent>(
                        "New World Environment", "Applies New World level lighting")
                    ->ClassElement(AZ::Edit::ClassElements::EditorData, "")
                    ->Attribute(AZ::Edit::Attributes::Category, "New World")
                    ->Attribute(AZ::Edit::Attributes::AppearsInAddComponentMenu, AZ_CRC_CE("Game"))
                    ->Attribute(AZ::Edit::Attributes::AutoExpand, true)
                    ->DataElement(AZ::Edit::UIHandlers::Default, &EditorNWEnvironmentComponent::m_config,
                        "Configuration", "New World environment settings");
            }
        }
    }

    void EditorNWEnvironmentComponent::GetProvidedServices(AZ::ComponentDescriptor::DependencyArrayType& provided)
    {
        provided.push_back(AZ_CRC_CE("NWEnvironmentService"));
    }

    void EditorNWEnvironmentComponent::GetIncompatibleServices(
        AZ::ComponentDescriptor::DependencyArrayType& incompatible)
    {
        incompatible.push_back(AZ_CRC_CE("NWEnvironmentService"));
    }

    void EditorNWEnvironmentComponent::GetRequiredServices(AZ::ComponentDescriptor::DependencyArrayType& required)
    {
        AZ_UNUSED(required);
    }

    void EditorNWEnvironmentComponent::Activate()
    {
        AZ::Entity* entity = GetEntity();
        if (!entity)
        {
            return;
        }
        m_runtimeComponent = entity->FindComponent<NWEnvironmentComponent>();
        if (!m_runtimeComponent)
        {
            // The entity is active in the editor, so the component is
            // initialised and activated by CreateComponent.
            m_runtimeComponent = entity->CreateComponent<NWEnvironmentComponent>(m_config);
        }
        ApplyConfiguration();
    }

    void EditorNWEnvironmentComponent::Deactivate()
    {
        if (m_runtimeComponent && GetEntity())
        {
            GetEntity()->RemoveComponent(m_runtimeComponent);
        }
        m_runtimeComponent = nullptr;
    }

    void EditorNWEnvironmentComponent::SetConfiguration(const NWEnvironmentConfig& config)
    {
        m_config = config;
        ApplyConfiguration();
    }

    const NWEnvironmentConfig& EditorNWEnvironmentComponent::GetConfiguration() const
    {
        return m_config;
    }

    void EditorNWEnvironmentComponent::ApplyConfiguration()
    {
        if (m_runtimeComponent)
        {
            m_runtimeComponent->SetConfiguration(m_config);
        }
    }

    void EditorNWEnvironmentComponent::BuildGameEntity(AZ::Entity* gameEntity)
    {
        gameEntity->CreateComponent<NWEnvironmentComponent>(m_config);
    }
} // namespace NWLighting
