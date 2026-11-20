/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 */

#pragma once

#include <AzToolsFramework/ToolsComponents/EditorComponentBase.h>
#include <NWLighting/Components/NWEnvironmentComponent.h>

namespace NWLighting
{
    //! Editor wrapper for NWEnvironmentComponent. Adds the runtime
    //! component when the entity is activated in the editor so the
    //! lighting applies immediately and travels with the prefab.
    class EditorNWEnvironmentComponent final : public AzToolsFramework::Components::EditorComponentBase
    {
    public:
        AZ_EDITOR_COMPONENT(
            EditorNWEnvironmentComponent, "{8C3F4D9E-5F60-4172-AC83-94D5E6F70819}", EditorComponentBase);

        static void Reflect(AZ::ReflectContext* context);
        static void GetProvidedServices(AZ::ComponentDescriptor::DependencyArrayType& provided);
        static void GetIncompatibleServices(AZ::ComponentDescriptor::DependencyArrayType& incompatible);
        static void GetRequiredServices(AZ::ComponentDescriptor::DependencyArrayType& required);

        EditorNWEnvironmentComponent() = default;

        void SetConfiguration(const NWEnvironmentConfig& config);
        const NWEnvironmentConfig& GetConfiguration() const;

        // EditorComponentBase overrides
        void Activate() override;
        void Deactivate() override;
        void BuildGameEntity(AZ::Entity* gameEntity) override;

    private:
        void ApplyConfiguration();

        NWEnvironmentConfig m_config;
        NWEnvironmentComponent* m_runtimeComponent = nullptr;
    };
} // namespace NWLighting
